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
from aether.lighting.zones import ZoneManager
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
    adapter = GoveeAdapter(mqtt, config.zones, topic_prefix=config.mqtt.topic_prefix)
    zones = ZoneManager(adapter)
    state_machine = StateMachine()
    circadian = CircadianEngine(config, zones)
    presence = PresenceDetector(config.presence, state_machine)
    camera = Camera(config.presence.camera_index, config.presence.frame_interval_ms)
    sentry = SentryAlert(
        adapter=adapter,
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
        adapter.publish_state(t.to_state.value)
        adapter.publish_transition(t.from_state.value, t.to_state.value, t.reason)
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
            focus = FocusMode(config.focus, zones, mode_cancel, mode_pause)
            _start_mode(focus.run())

        elif t.to_state == State.PARTY:
            party = DJMode(config.party, zones, mqtt, mode_cancel, mode_pause)
            _start_mode(party.run())

        elif t.to_state == State.SLEEP:
            sleep = SleepMode(config.sleep, zones, mqtt, mode_cancel, mode_pause)
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

    def _handle_mqtt_command(topic: str, payload: str):
        loop.call_soon_threadsafe(_handle_mqtt_command_inner, topic, payload)

    mqtt.on_message = _handle_mqtt_command
    mqtt.subscribe(f"{config.mqtt.topic_prefix}/mode/set")
    mqtt.subscribe(f"{config.mqtt.topic_prefix}/control")

    original_update = presence.tracker.update

    def update_with_mqtt(human_detected: bool, now: float | None = None):
        nonlocal alert_task
        adapter.publish_presence(human_detected)

        if human_detected and state_machine.state == State.AWAY:
            if alert_task is None or alert_task.done():
                alert_task = asyncio.ensure_future(sentry.trigger())

        original_update(human_detected, now)

    presence.tracker.update = update_with_mqtt

    print("[aether] Daemon running. Press Ctrl+C to stop.", file=sys.stderr)

    try:
        await asyncio.gather(
            camera.run(presence.process_frame),
            circadian.run(),
            mqtt.run(),
        )
    except KeyboardInterrupt:
        print("\n[aether] Shutting down...", file=sys.stderr)
    finally:
        _stop_active_mode()
        camera.release()
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
