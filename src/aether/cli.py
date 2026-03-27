# src/aether/cli.py
from __future__ import annotations

import asyncio
import sys

import click

from aether.config import load_config
from aether.state import StateMachine, State, Transition
from aether.vision.camera import Camera
from aether.vision.presence import PresenceDetector
from aether.lighting.circadian import CircadianEngine
from aether.lighting.zones import ZoneManager
from aether.adapters.mqtt import MqttClient
from aether.adapters.govee import GoveeAdapter
from aether.alerts.sentry import SentryAlert


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

    def handle_transition(t: Transition):
        nonlocal alert_task
        print(f"[aether] {t.from_state.value} → {t.to_state.value} ({t.reason})", file=sys.stderr)
        adapter.publish_state(t.to_state.value)
        adapter.publish_transition(t.from_state.value, t.to_state.value, t.reason)
        circadian.on_state_change(t.to_state)

        if t.to_state == State.PRESENT and t.from_state == State.AWAY:
            asyncio.ensure_future(circadian.run_return_ramp())

    state_machine._on_transition = handle_transition

    # Wrap presence to also publish MQTT + trigger sentry
    original_update = presence.tracker.update

    def update_with_mqtt(human_detected: bool, now: float | None = None):
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
        camera.release()
        mqtt.disconnect()


@cli.command()
def status():
    """Show current Aether state (reads from MQTT retained messages)."""
    import json
    import paho.mqtt.client as paho_mqtt

    results = {}
    topics = [
        "aether/state",
        "aether/presence/human",
        "aether/presence/last_seen",
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

    # Filter to real light devices (skip BaseGroup and other non-lights)
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

    # govee2mqtt uses colons in device IDs, but MQTT topics use them without colons
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

    # Write back to config
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
