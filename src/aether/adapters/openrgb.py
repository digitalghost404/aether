from __future__ import annotations

import asyncio
import json
import sys
import time
from typing import Any

try:
    from openrgb import OpenRGBClient
    from openrgb.utils import RGBColor
    HAS_OPENRGB = True
except ImportError:
    HAS_OPENRGB = False
    OpenRGBClient = None

    class RGBColor:  # type: ignore[no-redef]
        """Minimal fallback used when openrgb-python is not installed."""

        def __init__(self, red: int, green: int, blue: int) -> None:
            self.red = red
            self.green = green
            self.blue = blue


class OpenRGBAdapter:
    def __init__(
        self,
        mqtt_client,
        zones_config: dict,
        host: str = "localhost",
        port: int = 6820,
        topic_prefix: str = "aether",
        retry_attempts: int = 3,
        retry_delay_sec: float = 2.0,
    ):
        self._mqtt = mqtt_client
        self._zones = zones_config
        self._host = host
        self._port = port
        self._prefix = topic_prefix
        self._retry_attempts = retry_attempts
        self._retry_delay_sec = retry_delay_sec
        self._client: Any | None = None
        self._device_map: dict[str, list] = {}
        self._connected = False

    def connect(self) -> None:
        import aether.adapters.openrgb as _mod
        if _mod.OpenRGBClient is None:
            print(
                "[aether] openrgb-python not installed — OpenRGB adapter disabled",
                file=sys.stderr,
            )
            return

        for attempt in range(1, self._retry_attempts + 1):
            try:
                self._client = _mod.OpenRGBClient(self._host, self._port, name="aether")
                break
            except Exception as e:
                if attempt < self._retry_attempts:
                    print(f"[aether] OpenRGB connection attempt {attempt}/{self._retry_attempts} failed: {e}", file=sys.stderr)
                    time.sleep(self._retry_delay_sec)
                else:
                    print(f"[aether] OpenRGB connection failed after {self._retry_attempts} attempts: {e}", file=sys.stderr)
                    self._publish_status("disconnected")
                    return

        try:
            self._map_devices()
        except Exception as e:
            print(f"[aether] OpenRGB device mapping failed: {e}", file=sys.stderr)
            self._publish_status("disconnected")
            self._client = None
            return
        self._connected = True

    def _map_devices(self) -> None:
        if self._client is None:
            return

        server_devices = {d.name: d for d in self._client.devices}
        all_found = True

        for zone_name, zone_cfg in self._zones.items():
            devices = getattr(zone_cfg, "openrgb_devices", None)
            if not devices:
                continue

            matched = []
            for dev_name in devices:
                device = server_devices.get(dev_name)
                if device is not None:
                    matched.append(device)
                    try:
                        device.set_mode("direct")
                    except Exception:
                        pass  # some devices don't support Direct mode
                else:
                    print(
                        f"[aether] OpenRGB device not found: {dev_name!r} (zone: {zone_name})",
                        file=sys.stderr,
                    )
                    all_found = False

            self._device_map[zone_name] = matched

        status = "connected" if all_found else "degraded"
        self._publish_status(status)

        found_names = []
        for devices in self._device_map.values():
            found_names.extend(d.name for d in devices)
        self._mqtt.publish(
            f"{self._prefix}/peripheral/devices",
            json.dumps(found_names),
            retain=True,
        )

    def publish_zone(self, zone: str, color: dict) -> None:
        if not self._connected:
            return

        devices = self._device_map.get(zone)
        if not devices:
            return

        r = color.get("r", 0)
        g = color.get("g", 0)
        b = color.get("b", 0)
        brightness = color.get("brightness", 100)

        scaled_r = r * brightness // 100
        scaled_g = g * brightness // 100
        scaled_b = b * brightness // 100

        rgb = RGBColor(scaled_r, scaled_g, scaled_b)

        for device in devices:
            try:
                device.set_color(rgb)
            except Exception as e:
                print(
                    f"[aether] OpenRGB set_color failed for {device.name}: {e}",
                    file=sys.stderr,
                )

        self._mqtt.publish(
            f"{self._prefix}/peripheral/zone/{zone}",
            json.dumps(color),
            retain=True,
        )

    def disconnect(self) -> None:
        if self._client is not None:
            try:
                self._client.disconnect()
            except Exception:
                pass
            self._client = None
        self._connected = False
        self._device_map.clear()

    async def run_reconnect_loop(self, on_reconnect=None, interval: float = 30.0) -> None:
        """Background task: attempts to reconnect to OpenRGB server if disconnected."""
        import aether.adapters.openrgb as _mod
        while True:
            await asyncio.sleep(interval)
            if self._connected:
                continue
            if _mod.OpenRGBClient is None:
                continue
            try:
                self._client = _mod.OpenRGBClient(self._host, self._port, name="aether")
            except Exception:
                continue
            try:
                self._map_devices()
            except Exception:
                self._client = None
                continue
            self._connected = True
            print("[aether] OpenRGB reconnected", file=sys.stderr)
            if on_reconnect:
                on_reconnect()

    def _publish_status(self, status: str) -> None:
        self._mqtt.publish(
            f"{self._prefix}/peripheral/status",
            json.dumps(status),
            retain=True,
        )
