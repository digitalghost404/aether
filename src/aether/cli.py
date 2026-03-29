# src/aether/cli.py
from __future__ import annotations

import asyncio
import json
import sys

import click

from aether.config import load_config
from aether.state import StateMachine, State, Event, Transition
from aether.vision.camera import Camera
from aether.vision.presence import PresenceDetector
from aether.lighting.circadian import CircadianEngine
from aether.lighting.ramp import ColorState
from aether.lighting.zones import ZoneManager
from aether.mixer import Mixer
from aether.adapters.mqtt import MqttClient
from aether.adapters.govee import GoveeAdapter
from aether.alerts.sentry import SentryAlert
from aether.modes.focus import FocusMode
from aether.modes.sleep import SleepMode
from aether.modes.dj import DJMode


@click.group()
def cli():
    """Aether — The Living Room"""
    pass


@cli.command()
@click.option("--config", "config_path", type=click.Path(), default=None, help="Config file path")
def run(config_path):
    """Start the Aether daemon."""
    from pathlib import Path

    path = Path(config_path) if config_path else None
    config = load_config(path)

    print("[aether] Starting daemon...", file=sys.stderr)
    asyncio.run(_run_daemon(config))


async def _run_daemon(config):
    loop = asyncio.get_running_loop()
    mqtt = MqttClient(broker=config.mqtt.broker, port=config.mqtt.port)
    govee_adapter = GoveeAdapter(mqtt, config.zones, topic_prefix=config.mqtt.topic_prefix)

    # Build adapter routing: zone_name -> adapter instance
    adapters: dict = {}
    for zone_name, zone_cfg in config.zones.items():
        if zone_cfg.govee_device is not None:
            adapters[zone_name] = govee_adapter

    # OpenRGB adapter (optional)
    openrgb_adapter = None
    if config.openrgb.enabled:
        from aether.adapters.openrgb import OpenRGBAdapter

        openrgb_adapter = OpenRGBAdapter(
            mqtt, config.zones,
            host=config.openrgb.host,
            port=config.openrgb.port,
            topic_prefix=config.mqtt.topic_prefix,
            retry_attempts=config.openrgb.retry_attempts,
            retry_delay_sec=config.openrgb.retry_delay_sec,
        )
        openrgb_adapter.connect()
        for zone_name, zone_cfg in config.zones.items():
            if zone_cfg.openrgb_devices:
                adapters[zone_name] = openrgb_adapter

    zones = ZoneManager(adapters)
    mixer = Mixer(zones)

    # Scene engine (Govee Platform API for segmented device control)
    import os
    scene_engine = None
    govee_api_key = os.environ.get("GOVEE_API_KEY") or (
        config.govee_api.api_key if config.govee_api.api_key else None
    )

    if config.scenes and govee_api_key:
        from aether.adapters.govee_segment import GoveeSegmentAdapter
        from aether.scenes.engine import SceneEngine

        segment_adapter = GoveeSegmentAdapter(api_key=govee_api_key)
        scene_engine = SceneEngine(
            config=config,
            segment_adapter=segment_adapter,
            mixer=mixer,
            mqtt=mqtt,
        )
        print("[aether] Scene engine initialized", file=sys.stderr)
    elif config.scenes and not govee_api_key:
        print(
            "[aether] WARNING: Scenes defined but GOVEE_API_KEY not set. "
            "Scene engine disabled — falling back to palette circadian.",
            file=sys.stderr,
        )

    state_machine = StateMachine()
    circadian = CircadianEngine(config, mixer, scene_engine=scene_engine)

    # Gesture classifier (conditional — only if enabled and model available)
    gesture_classifier = None
    if config.gestures.enabled:
        from aether.vision.gestures import GestureClassifier, Gesture
        gesture_classifier = GestureClassifier(config.gestures)

    def _on_gesture_landmarks(landmarks):
        if gesture_classifier is None:
            return
        from aether.vision.gestures import Gesture
        gesture = gesture_classifier.update(landmarks)
        if gesture is None:
            return
        print(f"[aether] Gesture: {gesture.value}", file=sys.stderr)
        if config.gestures.feedback_flash:
            flash = ColorState(r=255, g=255, b=255, brightness=100)
            mixer.submit("feedback", "floor", flash, priority=0, ttl_sec=1)
            mixer.resolve()
        from datetime import datetime, timezone
        mqtt.publish("aether/gesture/last", {
            "gesture": gesture.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, retain=True)
        # Map gesture to action
        if gesture == Gesture.THUMBS_UP:
            claims = mixer.get_active_claims()
            for zone_name, claim in claims.items():
                new_br = min(100, claim.color.brightness + 20)
                new_color = ColorState(r=claim.color.r, g=claim.color.g, b=claim.color.b, brightness=new_br)
                mixer.submit("gesture", zone_name, new_color, priority=0, ttl_sec=config.mixer.manual_ttl_sec)
            mixer.resolve()
        elif gesture == Gesture.THUMBS_DOWN:
            claims = mixer.get_active_claims()
            for zone_name, claim in claims.items():
                new_br = max(0, claim.color.brightness - 20)
                new_color = ColorState(r=claim.color.r, g=claim.color.g, b=claim.color.b, brightness=new_br)
                mixer.submit("gesture", zone_name, new_color, priority=0, ttl_sec=config.mixer.manual_ttl_sec)
            mixer.resolve()
        elif gesture == Gesture.FIST:
            if zones.paused:
                loop.call_soon_threadsafe(
                    _handle_mqtt_command_inner,
                    f"{config.mqtt.topic_prefix}/control", "resume"
                )
            else:
                loop.call_soon_threadsafe(
                    _handle_mqtt_command_inner,
                    f"{config.mqtt.topic_prefix}/control", "pause"
                )

    gesture_cb = _on_gesture_landmarks if gesture_classifier else None
    presence = PresenceDetector(config.presence, state_machine, gesture_callback=gesture_cb)
    camera = Camera(config.presence.camera_index, config.presence.frame_interval_ms)
    sentry = SentryAlert(
        adapter=govee_adapter,
        floor_zone_name="floor",
        flash_color=config.alerts.sentry.floor_flash_color,
        flash_count=config.alerts.sentry.floor_flash_count,
    )

    alert_task = None
    active_mode_task = None
    mode_cancel = asyncio.Event()
    mode_pause = asyncio.Event()

    def _stop_active_mode():
        nonlocal active_mode_task
        if active_mode_task and not active_mode_task.done():
            mode_cancel.set()
            active_mode_task = None

    def _start_mode(coro):
        nonlocal active_mode_task
        mode_cancel.clear()
        active_mode_task = asyncio.ensure_future(coro)

        async def _on_mode_done(task):
            try:
                await task
            except Exception as e:
                print(f"[aether] Mode error: {e}", file=sys.stderr)
            if not mode_cancel.is_set():
                if state_machine.state == State.FOCUS:
                    state_machine.handle_event(Event.FOCUS_STOP)
                elif state_machine.state == State.PARTY:
                    state_machine.handle_event(Event.PARTY_STOP)
                elif state_machine.state == State.SLEEP:
                    state_machine.handle_event(Event.SLEEP_COMPLETE)

        asyncio.ensure_future(_on_mode_done(active_mode_task))

    def handle_transition(t: Transition):
        nonlocal alert_task
        print(f"[aether] {t.from_state.value} → {t.to_state.value} ({t.reason})", file=sys.stderr)
        govee_adapter.publish_state(t.to_state.value)
        govee_adapter.publish_transition(t.from_state.value, t.to_state.value, t.reason)
        circadian.on_state_change(t.to_state)

        if t.to_state == State.PRESENT and t.from_state == State.AWAY:
            # Cancel any in-flight sentry alert so it doesn't race the ramp
            if alert_task and not alert_task.done():
                alert_task.cancel()
            asyncio.ensure_future(circadian.run_return_ramp())

        if t.to_state == State.PRESENT and t.from_state in (State.FOCUS, State.PARTY, State.SLEEP):
            _stop_active_mode()
            asyncio.ensure_future(circadian.run_return_ramp())

        if t.to_state == State.FOCUS:
            focus = FocusMode(config.focus, mixer, mode_cancel, mode_pause)
            _start_mode(focus.run())

        elif t.to_state == State.PARTY:
            party = DJMode(config.party, mixer, mqtt, mode_cancel, mode_pause)
            _start_mode(party.run())

        elif t.to_state == State.SLEEP:
            sleep = SleepMode(config.sleep, mixer, mqtt, mode_cancel, mode_pause)
            _start_mode(sleep.run())

        elif t.to_state == State.AWAY and t.from_state == State.SLEEP:
            _stop_active_mode()

    state_machine._on_transition = handle_transition

    def _handle_mqtt_command_inner(topic: str, payload: str):
        payload = payload.strip().strip('"')
        if topic == f"{config.mqtt.topic_prefix}/mode/set":
            if payload == "focus" and state_machine.state == State.PRESENT:
                state_machine.handle_event(Event.FOCUS_START)
            elif payload == "party" and state_machine.state == State.PRESENT:
                state_machine.handle_event(Event.PARTY_START)
            elif payload == "sleep" and state_machine.state == State.PRESENT:
                state_machine.handle_event(Event.SLEEP_START)
            elif payload == "focus_stop" and state_machine.state == State.FOCUS:
                state_machine.handle_event(Event.FOCUS_STOP)
            elif payload == "party_stop" and state_machine.state == State.PARTY:
                state_machine.handle_event(Event.PARTY_STOP)
            elif payload == "sleep_stop" and state_machine.state == State.SLEEP:
                state_machine.handle_event(Event.SLEEP_CANCEL)
        elif topic == f"{config.mqtt.topic_prefix}/control":
            if payload == "pause":
                zones.paused = True
                mode_pause.set()
                mqtt.publish(f"{config.mqtt.topic_prefix}/paused", json.dumps(True), retain=True)
                print("[aether] Paused", file=sys.stderr)
            elif payload == "resume":
                zones.paused = False
                mode_pause.clear()
                zones.flush_current()
                mqtt.publish(f"{config.mqtt.topic_prefix}/paused", json.dumps(False), retain=True)
                print("[aether] Resumed", file=sys.stderr)
        elif topic == f"{config.mqtt.topic_prefix}/scene/set":
            if scene_engine is not None:
                try:
                    cmd = json.loads(payload)
                    action = cmd.get("action")
                    if action == "set":
                        name = cmd.get("name", "")
                        asyncio.ensure_future(scene_engine.apply_scene(name, manual=True))
                    elif action == "random":
                        import random as _random
                        names = scene_engine.get_scene_names()
                        if names:
                            asyncio.ensure_future(
                                scene_engine.apply_scene(_random.choice(names), manual=True)
                            )
                    elif action == "reset":
                        scene_engine.reset_to_circadian()
                except json.JSONDecodeError:
                    asyncio.ensure_future(scene_engine.apply_scene(payload, manual=True))

    def _handle_mqtt_command(topic: str, payload: str):
        loop.call_soon_threadsafe(_handle_mqtt_command_inner, topic, payload)

    mqtt.on_message = _handle_mqtt_command
    mqtt.subscribe(f"{config.mqtt.topic_prefix}/mode/set")
    mqtt.subscribe(f"{config.mqtt.topic_prefix}/control")
    mqtt.subscribe(f"{config.mqtt.topic_prefix}/scene/set")

    original_update = presence.tracker.update

    def update_with_mqtt(human_detected: bool, now: float | None = None):
        nonlocal alert_task
        govee_adapter.publish_presence(human_detected)

        if human_detected and state_machine.state == State.AWAY:
            if alert_task is None or alert_task.done():
                alert_task = asyncio.ensure_future(sentry.trigger())

        original_update(human_detected, now)

    presence.tracker.update = update_with_mqtt

    print("[aether] Daemon running. Press Ctrl+C to stop.", file=sys.stderr)

    coros = [
        camera.run(presence.process_frame),
        circadian.run(),
        mqtt.run(),
        mixer.run(tick_interval=config.mixer.tick_interval_sec),
    ]

    if openrgb_adapter is not None:
        coros.append(openrgb_adapter.run_reconnect_loop(on_reconnect=zones.flush_current))

    if config.vox.enabled:
        from aether.vox.mic import MicCapture
        from aether.vox.wake import WakeWordDetector
        from aether.vox.stt import SpeechToText
        from aether.vox.intent import classify_intent
        from aether.vox.handler import VoxHandler

        async def _vox_pipeline():
            mic = MicCapture(config.vox.mic_source)
            if not await mic.start():
                return
            wake = WakeWordDetector(config.vox.wake_word)
            if not wake.load():
                mic.stop()
                return
            stt = SpeechToText(config.vox.whisper_model)
            handler = VoxHandler(state_machine, mixer, mqtt, config, scene_engine=scene_engine)
            print("[aether] VOX: pipeline ready", file=sys.stderr)
            try:
                while True:
                    chunk = await mic.read_chunk()
                    if chunk is None:
                        break
                    if wake.detect(chunk):
                        print("[aether] VOX: wake word detected", file=sys.stderr)
                        if config.vox.feedback_flash:
                            flash = ColorState(r=255, g=255, b=255, brightness=100)
                            mixer.submit("feedback", "floor", flash, priority=0, ttl_sec=1)
                            mixer.resolve()
                        audio = await mic.read_seconds(
                            config.vox.command_timeout_sec,
                            silence_timeout=config.vox.silence_timeout_sec,
                        )
                        if len(audio) == 0:
                            continue
                        text = await asyncio.to_thread(stt.transcribe, audio)
                        if text is None:
                            continue
                        print(f"[aether] VOX: heard: {text!r}", file=sys.stderr)
                        intent = classify_intent(text)
                        if intent is None:
                            print(f"[aether] VOX: no keyword match for {text!r}, skipping", file=sys.stderr)
                            continue
                        handler.execute(intent, text)
            finally:
                mic.stop()

        coros.append(_vox_pipeline())

    try:
        await asyncio.gather(*coros)
    except KeyboardInterrupt:
        print("\n[aether] Shutting down...", file=sys.stderr)
    finally:
        _stop_active_mode()
        camera.release()
        if openrgb_adapter is not None:
            openrgb_adapter.disconnect()
        mqtt.disconnect()


def _publish_command(broker: str, port: int, topic: str, payload: str):
    import paho.mqtt.client as paho_mqtt

    client = paho_mqtt.Client(paho_mqtt.CallbackAPIVersion.VERSION2)
    client.connect(broker, port)
    client.publish(topic, payload, qos=1)
    client.disconnect()


@cli.command()
@click.option("--cycles", default=None, type=int, help="Number of Pomodoro cycles (0=indefinite)")
@click.option("--work", default=None, type=int, help="Work period in minutes")
@click.option("--break", "break_min", default=None, type=int, help="Short break in minutes")
@click.option("--config", "config_path", type=click.Path(), default=None)
def focus(cycles, work, break_min, config_path):
    """Enter FOCUS mode (Pomodoro)."""
    from pathlib import Path
    config = load_config(Path(config_path) if config_path else None)
    _publish_command(config.mqtt.broker, config.mqtt.port,
                     f"{config.mqtt.topic_prefix}/mode/set", "focus")
    click.echo("FOCUS mode activated.")


@cli.command("focus-stop")
@click.option("--config", "config_path", type=click.Path(), default=None)
def focus_stop(config_path):
    """Exit FOCUS mode."""
    from pathlib import Path
    config = load_config(Path(config_path) if config_path else None)
    _publish_command(config.mqtt.broker, config.mqtt.port,
                     f"{config.mqtt.topic_prefix}/mode/set", "focus_stop")
    click.echo("FOCUS mode stopped.")


@cli.command()
@click.option("--config", "config_path", type=click.Path(), default=None)
def party(config_path):
    """Enter PARTY mode (DJ Lightshow)."""
    from pathlib import Path
    config = load_config(Path(config_path) if config_path else None)
    _publish_command(config.mqtt.broker, config.mqtt.port,
                     f"{config.mqtt.topic_prefix}/mode/set", "party")
    click.echo("PARTY mode activated.")


@cli.command("party-stop")
@click.option("--config", "config_path", type=click.Path(), default=None)
def party_stop(config_path):
    """Exit PARTY mode."""
    from pathlib import Path
    config = load_config(Path(config_path) if config_path else None)
    _publish_command(config.mqtt.broker, config.mqtt.port,
                     f"{config.mqtt.topic_prefix}/mode/set", "party_stop")
    click.echo("PARTY mode stopped.")


@cli.command()
@click.option("--config", "config_path", type=click.Path(), default=None)
def sleep(config_path):
    """Enter SLEEP mode (cascade shutdown)."""
    from pathlib import Path
    config = load_config(Path(config_path) if config_path else None)
    _publish_command(config.mqtt.broker, config.mqtt.port,
                     f"{config.mqtt.topic_prefix}/mode/set", "sleep")
    click.echo("SLEEP mode activated.")


@cli.command("sleep-stop")
@click.option("--config", "config_path", type=click.Path(), default=None)
def sleep_stop(config_path):
    """Cancel SLEEP mode."""
    from pathlib import Path
    config = load_config(Path(config_path) if config_path else None)
    _publish_command(config.mqtt.broker, config.mqtt.port,
                     f"{config.mqtt.topic_prefix}/mode/set", "sleep_stop")
    click.echo("SLEEP mode cancelled.")


@cli.command()
@click.option("--config", "config_path", type=click.Path(), default=None)
def pause(config_path):
    """Pause all light output."""
    from pathlib import Path
    config = load_config(Path(config_path) if config_path else None)
    _publish_command(config.mqtt.broker, config.mqtt.port,
                     f"{config.mqtt.topic_prefix}/control", "pause")
    click.echo("Aether paused.")


@cli.command()
@click.option("--config", "config_path", type=click.Path(), default=None)
def resume(config_path):
    """Resume light output."""
    from pathlib import Path
    config = load_config(Path(config_path) if config_path else None)
    _publish_command(config.mqtt.broker, config.mqtt.port,
                     f"{config.mqtt.topic_prefix}/control", "resume")
    click.echo("Aether resumed.")


@cli.command("scene")
@click.argument("name", required=False)
@click.option("--random", "use_random", is_flag=True, help="Apply a random scene")
@click.option("--reset", "use_reset", is_flag=True, help="Reset to circadian default")
@click.option("--list", "use_list", is_flag=True, help="List available scenes")
@click.option("--config", "config_path", type=click.Path(), default=None)
def scene(name, use_random, use_reset, use_list, config_path):
    """Apply a lighting scene."""
    from pathlib import Path
    config = load_config(Path(config_path) if config_path else None)

    if use_list:
        if not config.scenes:
            click.echo("No scenes defined in config.")
            return
        click.echo("Available scenes:")
        for scene_name in sorted(config.scenes.keys()):
            click.echo(f"  {scene_name}")
        return

    broker = config.mqtt.broker
    port = config.mqtt.port
    topic = f"{config.mqtt.topic_prefix}/scene/set"

    if use_reset:
        _publish_command(broker, port, topic, json.dumps({"action": "reset"}))
        click.echo("Reset to circadian lighting.")
    elif use_random:
        _publish_command(broker, port, topic, json.dumps({"action": "random"}))
        click.echo("Random scene applied.")
    elif name:
        _publish_command(broker, port, topic, json.dumps({"action": "set", "name": name}))
        click.echo(f"Scene '{name}' applied.")
    else:
        click.echo("Specify a scene name, or use --random, --reset, or --list.")


@cli.command("vox-test")
@click.option("--config", "config_path", type=click.Path(), default=None)
def vox_test(config_path):
    """Test the voice pipeline — prints wake word detections and transcriptions."""
    from pathlib import Path
    config = load_config(Path(config_path) if config_path else None)
    asyncio.run(_vox_test(config))


async def _vox_test(config):
    from aether.vox.mic import MicCapture
    from aether.vox.wake import WakeWordDetector
    from aether.vox.stt import SpeechToText
    from aether.vox.intent import classify_intent

    mic = MicCapture(config.vox.mic_source)
    if not await mic.start():
        return
    wake = WakeWordDetector(config.vox.wake_word)
    if not wake.load():
        mic.stop()
        return
    stt = SpeechToText(config.vox.whisper_model)
    print("Listening for wake word... (Ctrl+C to stop)")
    try:
        while True:
            chunk = await mic.read_chunk()
            if chunk is None:
                break
            if wake.detect(chunk):
                print(">>> Wake word detected! Recording command...")
                audio = await mic.read_seconds(
                    config.vox.command_timeout_sec,
                    silence_timeout=config.vox.silence_timeout_sec,
                )
                if len(audio) == 0:
                    print(">>> No audio captured")
                    continue
                text = await asyncio.to_thread(stt.transcribe, audio)
                if text:
                    intent = classify_intent(text)
                    print(f">>> Heard: {text!r} → Intent: {intent}")
                else:
                    print(">>> Transcription failed")
    except KeyboardInterrupt:
        pass
    finally:
        mic.stop()


@cli.command()
def status():
    """Show current Aether state."""
    import paho.mqtt.client as paho_mqtt

    results = {}
    topics = [
        "aether/state",
        "aether/presence/human",
        "aether/presence/last_seen",
        "aether/paused",
        "aether/focus/state",
        "aether/focus/timer",
        "aether/sleep/stage",
    ]

    def on_connect(client, userdata, flags, rc, properties=None):
        for t in topics:
            client.subscribe(t)

    def on_message(client, userdata, msg):
        results[msg.topic] = msg.payload.decode()
        if len(results) >= len(topics):
            client.disconnect()

    client = paho_mqtt.Client(paho_mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect("localhost", 1883)
        client.loop_start()

        import time
        deadline = time.time() + 3
        while len(results) < len(topics) and time.time() < deadline:
            time.sleep(0.1)

        client.loop_stop()
        client.disconnect()
    except Exception as e:
        click.echo(f"Cannot connect to MQTT broker: {e}", err=True)
        sys.exit(1)

    click.echo(f"State:     {results.get('aether/state', 'unknown')}")
    click.echo(f"Human:     {results.get('aether/presence/human', 'unknown')}")
    click.echo(f"Last seen: {results.get('aether/presence/last_seen', 'unknown')}")
    click.echo(f"Paused:    {results.get('aether/paused', 'false')}")

    focus_state = results.get("aether/focus/state")
    if focus_state:
        click.echo(f"Focus:     {focus_state}")
    focus_timer = results.get("aether/focus/timer")
    if focus_timer:
        try:
            timer = json.loads(focus_timer)
            click.echo(f"  Timer:   {timer['remaining_sec']}s remaining (cycle {timer['cycle']}/{timer['total_cycles']})")
        except Exception:
            pass

    sleep_stage = results.get("aether/sleep/stage")
    if sleep_stage:
        click.echo(f"Sleep:     {sleep_stage}")


@cli.command()
@click.option("--config", "config_path", type=click.Path(), default=None, help="Config file path")
def discover(config_path):
    """Discover Govee devices and map them to zones."""
    import json
    from pathlib import Path
    import httpx
    import yaml

    path = Path(config_path) if config_path else None
    config = load_config(path)
    config_file_path = path or (Path.home() / ".config" / "aether" / "config.yaml")

    click.echo("Querying govee2mqtt HTTP API for devices...")

    try:
        resp = httpx.get("http://localhost:8056/api/devices", timeout=5)
        resp.raise_for_status()
        all_devices = resp.json()
    except Exception as e:
        click.echo(f"Cannot connect to govee2mqtt API: {e}", err=True)
        click.echo("Is govee2mqtt running? (docker ps | grep govee2mqtt)", err=True)
        sys.exit(1)

    devices = [
        d for d in all_devices
        if d.get("sku", "").startswith("H") and d.get("name")
    ]

    if not devices:
        click.echo("No Govee light devices found.")
        sys.exit(1)

    click.echo(f"\nFound {len(devices)} Govee devices:")
    for i, dev in enumerate(devices, 1):
        state = dev.get("state", {})
        online = "online" if state and state.get("online") else "offline"
        on_off = "ON" if state and state.get("on") else "OFF"
        click.echo(f"  {i}. {dev['name']} ({dev['sku']}) [{online}, {on_off}]")

    def mqtt_device_id(raw_id: str) -> str:
        return raw_id.replace(":", "")

    zone_names = ["wall_left", "wall_right", "monitor", "floor", "bedroom"]
    zone_map = {}

    click.echo("\nMap devices to zones (enter number, or 0 to skip):")
    for zone in zone_names:
        while True:
            choice = click.prompt(f"  {zone}", type=int, default=0)
            if choice == 0:
                break
            if 1 <= choice <= len(devices):
                zone_map[zone] = mqtt_device_id(devices[choice - 1]["id"])
                break
            click.echo(f"  Invalid choice. Enter 1-{len(devices)} or 0 to skip.")

    with open(config_file_path) as f:
        raw = yaml.safe_load(f) or {}

    if "zones" not in raw:
        raw["zones"] = {}
    for zone, dev_id in zone_map.items():
        if zone not in raw["zones"]:
            raw["zones"][zone] = {}
        raw["zones"][zone]["govee_device"] = dev_id

    with open(config_file_path, "w") as f:
        yaml.dump(raw, f, default_flow_style=False)

    click.echo(f"\nConfig updated at {config_file_path}")
    click.echo("Mapped zones:")
    for zone, dev_id in zone_map.items():
        click.echo(f"  {zone} → {dev_id}")
