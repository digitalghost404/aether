# Phase 3 Peripherals — OpenRGB Desk Lighting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend Aether's lighting control to desk peripherals (keyboard, mouse, case LEDs, RAM) via OpenRGB, adding two new zones (`desk`, `tower`) that integrate into the existing mixer/zone architecture.

**Architecture:** New `OpenRGBAdapter` connects to OpenRGB SDK server over TCP (port 6820), maps zone names to device lists, and implements the same `publish_zone()` interface as `GoveeAdapter`. `ZoneManager` is refactored to route zones to adapters via a dict. `ZONE_NAMES` expands from 5 to 7. Modes gain desk/tower-specific lighting claims.

**Tech Stack:** Python 3.11+, openrgb-python (PyPI), existing paho-mqtt for observability topics.

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `src/aether/adapters/openrgb.py` | OpenRGB SDK adapter — connects to server, maps zones to devices, publishes color + MQTT status |
| Create | `tests/test_openrgb_adapter.py` | Unit tests for OpenRGB adapter |
| Modify | `src/aether/config.py` | Add `OpenRGBConfig`, extend `ZoneConfig` with `openrgb_devices`, add focus desk/tower fields |
| Modify | `tests/test_config.py` | Test new config fields |
| Modify | `src/aether/lighting/zones.py` | Refactor to multi-adapter routing via `dict[str, adapter]`, expand `ZONE_NAMES` to 7 |
| Modify | `tests/test_mixer.py` | Update `FakeZoneManager` and assertions for 7 zones |
| Modify | `tests/test_focus.py` | Update `FakeMixer.submit_all` zone list, add desk/tower assertions |
| Modify | `tests/test_dj.py` | Update `FakeMixer.submit_all` zone list, add tower/desk assertions |
| Modify | `src/aether/mixer.py` | Update `submit_all`, `resolve`, `get_active_claims` to use `ZONE_NAMES` from zones module |
| Modify | `src/aether/modes/focus.py` | Add desk (warm white) and tower (dim) claims |
| Modify | `src/aether/modes/dj.py` | Add tower (beat-sync) and desk (base accent) claims |
| Modify | `src/aether/cli.py` | Wire OpenRGB adapter into daemon startup, build adapter routing dict |
| Modify | `config.example.yaml` | Add `openrgb` section and desk/tower zone examples |
| Modify | `pyproject.toml` | Add `openrgb-python` to optional dependencies |

---

### Task 1: Add OpenRGB Config Models

**Files:**
- Modify: `src/aether/config.py:55-57` (ZoneConfig), `src/aether/config.py:125-137` (AetherConfig)
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write failing test for OpenRGBConfig defaults**

In `tests/test_config.py`, add:

```python
from aether.config import OpenRGBConfig


def test_openrgb_config_defaults():
    cfg = OpenRGBConfig()
    assert cfg.enabled is True
    assert cfg.host == "localhost"
    assert cfg.port == 6820
    assert cfg.retry_attempts == 3
    assert cfg.retry_delay_sec == 2.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/digitalghost/projects/aether && .venv/bin/pytest tests/test_config.py::test_openrgb_config_defaults -v`
Expected: FAIL with `ImportError: cannot import name 'OpenRGBConfig'`

- [ ] **Step 3: Implement OpenRGBConfig**

In `src/aether/config.py`, add after `GestureConfig` (line 122):

```python
class OpenRGBConfig(BaseModel):
    enabled: bool = True
    host: str = "localhost"
    port: int = 6820
    retry_attempts: int = 3
    retry_delay_sec: float = 2.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/digitalghost/projects/aether && .venv/bin/pytest tests/test_config.py::test_openrgb_config_defaults -v`
Expected: PASS

- [ ] **Step 5: Write failing test for ZoneConfig with openrgb_devices**

In `tests/test_config.py`, add:

```python
from aether.config import ZoneConfig


def test_zone_config_openrgb_devices():
    cfg = ZoneConfig(openrgb_devices=["SteelSeries Apex 3 TKL", "SteelSeries Rival 600"])
    assert cfg.openrgb_devices == ["SteelSeries Apex 3 TKL", "SteelSeries Rival 600"]
    assert cfg.govee_device is None


def test_zone_config_govee_device_no_openrgb():
    cfg = ZoneConfig(govee_device="AABBCCDDEEFF")
    assert cfg.govee_device == "AABBCCDDEEFF"
    assert cfg.openrgb_devices is None
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd /home/digitalghost/projects/aether && .venv/bin/pytest tests/test_config.py::test_zone_config_openrgb_devices -v`
Expected: FAIL with `unexpected keyword argument 'openrgb_devices'`

- [ ] **Step 7: Extend ZoneConfig and AetherConfig**

In `src/aether/config.py`, update `ZoneConfig` (line 55-56):

```python
class ZoneConfig(BaseModel):
    govee_device: str | None = None
    openrgb_devices: list[str] | None = None
```

Add `openrgb` field to `AetherConfig` (after `gestures` field):

```python
class AetherConfig(BaseModel):
    location: LocationConfig = LocationConfig()
    presence: PresenceConfig = PresenceConfig()
    mqtt: MqttConfig = MqttConfig()
    circadian: CircadianConfig = CircadianConfig()
    zones: dict[str, ZoneConfig] = {}
    alerts: AlertsConfig = AlertsConfig()
    focus: FocusConfig = FocusConfig()
    party: PartyConfig = PartyConfig()
    sleep: SleepConfig = SleepConfig()
    mixer: MixerConfig = MixerConfig()
    vox: VoxConfig = VoxConfig()
    gestures: GestureConfig = GestureConfig()
    openrgb: OpenRGBConfig = OpenRGBConfig()
```

- [ ] **Step 8: Write failing test for FocusConfig desk/tower fields**

In `tests/test_config.py`, add:

```python
from aether.config import FocusConfig


def test_focus_config_desk_tower_defaults():
    cfg = FocusConfig()
    assert cfg.desk_color == [255, 223, 191]
    assert cfg.desk_brightness == 80
    assert cfg.tower_brightness == 10
```

- [ ] **Step 9: Run test to verify it fails**

Run: `cd /home/digitalghost/projects/aether && .venv/bin/pytest tests/test_config.py::test_focus_config_desk_tower_defaults -v`
Expected: FAIL with `AttributeError`

- [ ] **Step 10: Add desk/tower fields to FocusConfig and PartyConfig**

In `src/aether/config.py`, extend `FocusConfig` (add after `break_brightness`):

```python
class FocusConfig(BaseModel):
    work_min: int = 25
    short_break_min: int = 5
    long_break_min: int = 15
    cycles: int = 4
    work_color: list[int] = [255, 255, 255]
    work_brightness: int = 100
    rope_dim_brightness: int = 10
    break_color: list[int] = [180, 230, 180]
    break_brightness: int = 10
    desk_color: list[int] = [255, 223, 191]
    desk_brightness: int = 80
    tower_brightness: int = 10
```

Extend `PartyConfig` (add after `palette`):

```python
class PartyConfig(BaseModel):
    accent_zone: str = "floor"
    accent_brightness_low: int = 40
    accent_brightness_high: int = 100
    base_shift_beats: int = 8
    silence_timeout_sec: int = 120
    palette: list[list[int]] = [
        [180, 50, 255],
        [255, 50, 150],
        [50, 220, 220],
        [255, 80, 50],
    ]
    tower_beat_sync: bool = True
    desk_accent: bool = True
```

- [ ] **Step 11: Run all config tests**

Run: `cd /home/digitalghost/projects/aether && .venv/bin/pytest tests/test_config.py tests/test_config_phase2.py tests/test_config_phase3.py -v`
Expected: ALL PASS

- [ ] **Step 12: Commit**

```bash
cd /home/digitalghost/projects/aether
git add src/aether/config.py tests/test_config.py
git commit -m "feat: add OpenRGBConfig, extend ZoneConfig and mode configs for peripherals"
```

---

### Task 2: Expand ZONE_NAMES and Refactor ZoneManager to Multi-Adapter

**Files:**
- Modify: `src/aether/lighting/zones.py`
- Modify: `tests/test_mixer.py` (FakeZoneManager uses ZONE_NAMES)

- [ ] **Step 1: Write failing test for 7-zone ZoneManager**

Create `tests/test_zones.py`:

```python
from unittest.mock import MagicMock
from aether.lighting.ramp import ColorState
from aether.lighting.zones import ZoneManager, ZONE_NAMES


def test_zone_names_includes_desk_and_tower():
    assert "desk" in ZONE_NAMES
    assert "tower" in ZONE_NAMES
    assert len(ZONE_NAMES) == 7


def test_zone_manager_routes_to_correct_adapter():
    govee = MagicMock()
    openrgb = MagicMock()
    adapters = {
        "wall_left": govee,
        "wall_right": govee,
        "monitor": govee,
        "floor": govee,
        "bedroom": govee,
        "desk": openrgb,
        "tower": openrgb,
    }
    zm = ZoneManager(adapters)
    red = ColorState(r=255, g=0, b=0, brightness=100)
    zm.set_zone("floor", red)
    govee.publish_zone.assert_called_once_with("floor", red.to_dict())
    openrgb.publish_zone.assert_not_called()


def test_zone_manager_routes_openrgb_zone():
    govee = MagicMock()
    openrgb = MagicMock()
    adapters = {
        "wall_left": govee,
        "wall_right": govee,
        "monitor": govee,
        "floor": govee,
        "bedroom": govee,
        "desk": openrgb,
        "tower": openrgb,
    }
    zm = ZoneManager(adapters)
    blue = ColorState(r=0, g=0, b=255, brightness=80)
    zm.set_zone("desk", blue)
    openrgb.publish_zone.assert_called_once_with("desk", blue.to_dict())
    govee.publish_zone.assert_not_called()


def test_set_all_covers_all_7_zones():
    adapter = MagicMock()
    adapters = {name: adapter for name in ZONE_NAMES}
    zm = ZoneManager(adapters)
    white = ColorState(r=255, g=255, b=255, brightness=100)
    zm.set_all(white)
    assert adapter.publish_zone.call_count == 7


def test_dedup_skips_unchanged():
    adapter = MagicMock()
    adapters = {"floor": adapter}
    zm = ZoneManager(adapters)
    red = ColorState(r=255, g=0, b=0, brightness=100)
    zm.set_zone("floor", red)
    zm.set_zone("floor", red)  # duplicate
    assert adapter.publish_zone.call_count == 1


def test_flush_current_republishes_all():
    adapter = MagicMock()
    adapters = {name: adapter for name in ZONE_NAMES}
    zm = ZoneManager(adapters)
    red = ColorState(r=255, g=0, b=0, brightness=100)
    zm.set_zone("floor", red)
    adapter.publish_zone.reset_mock()
    zm.flush_current()
    assert adapter.publish_zone.call_count == 7


def test_paused_skips_publish():
    adapter = MagicMock()
    adapters = {"floor": adapter}
    zm = ZoneManager(adapters)
    zm.paused = True
    red = ColorState(r=255, g=0, b=0, brightness=100)
    zm.set_zone("floor", red)
    adapter.publish_zone.assert_not_called()


def test_zone_without_adapter_is_skipped():
    adapters = {"floor": MagicMock()}  # desk not in dict
    zm = ZoneManager(adapters)
    blue = ColorState(r=0, g=0, b=255, brightness=100)
    zm.set_zone("desk", blue)  # should not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/digitalghost/projects/aether && .venv/bin/pytest tests/test_zones.py -v`
Expected: FAIL — `ZONE_NAMES` has 5 elements, `ZoneManager.__init__` expects single adapter

- [ ] **Step 3: Refactor ZoneManager**

Replace `src/aether/lighting/zones.py` entirely:

```python
from __future__ import annotations

from typing import Any

from aether.lighting.ramp import ColorState

ZONE_NAMES = ("wall_left", "wall_right", "monitor", "floor", "bedroom", "desk", "tower")


class ZoneManager:
    ZONE_NAMES = ZONE_NAMES

    def __init__(self, adapters: dict[str, Any]):
        self._adapters = adapters
        self._current: dict[str, ColorState] = {
            name: ColorState(r=0, g=0, b=0, brightness=0) for name in ZONE_NAMES
        }
        self.paused: bool = False

    def get(self, zone: str) -> ColorState:
        return self._current[zone]

    def set_zone(self, zone: str, state: ColorState) -> None:
        if self._current.get(zone) == state:
            return
        self._current[zone] = state
        if not self.paused:
            adapter = self._adapters.get(zone)
            if adapter is not None:
                adapter.publish_zone(zone, state.to_dict())

    def set_all(self, state: ColorState) -> None:
        for zone in ZONE_NAMES:
            self.set_zone(zone, state)

    def get_all(self) -> dict[str, ColorState]:
        return dict(self._current)

    def flush_current(self) -> None:
        """Re-publish all current zone states. Call after resume."""
        for zone, state in self._current.items():
            adapter = self._adapters.get(zone)
            if adapter is not None:
                adapter.publish_zone(zone, state.to_dict())
```

- [ ] **Step 4: Run zone tests**

Run: `cd /home/digitalghost/projects/aether && .venv/bin/pytest tests/test_zones.py -v`
Expected: ALL PASS

- [ ] **Step 5: Update FakeZoneManager in test_mixer.py**

In `tests/test_mixer.py`, the `FakeZoneManager` class (lines 9-17) does not use `ZONE_NAMES` directly — it's a simple mock. However, `test_submit_all_zones` (line 82) asserts `len(zm.calls) == 5`. Update to 7:

```python
def test_submit_all_zones():
    zm = FakeZoneManager()
    mixer = Mixer(zm)
    white = ColorState(r=255, g=255, b=255, brightness=100)
    mixer.submit_all("circadian", white, priority=2)
    mixer.resolve()
    assert len(zm.calls) == 7
```

- [ ] **Step 6: Run mixer tests**

Run: `cd /home/digitalghost/projects/aether && .venv/bin/pytest tests/test_mixer.py -v`
Expected: ALL PASS

- [ ] **Step 7: Update FakeMixer in test_focus.py**

In `tests/test_focus.py`, update `FakeMixer.submit_all` (line 17) to use 7 zones:

```python
    def submit_all(self, source: str, color: ColorState, priority: int, ttl_sec: float | None = None) -> None:
        for zone in ("wall_left", "wall_right", "monitor", "floor", "bedroom", "desk", "tower"):
            self.submit(source, zone, color, priority)
```

- [ ] **Step 8: Update FakeMixer in test_dj.py**

In `tests/test_dj.py`, update `FakeMixer.submit_all` (line 17) to use 7 zones:

```python
    def submit_all(self, source: str, color: ColorState, priority: int, ttl_sec: float | None = None) -> None:
        for zone in ("wall_left", "wall_right", "monitor", "floor", "bedroom", "desk", "tower"):
            self.submit(source, zone, color, priority)
```

- [ ] **Step 9: Run all tests**

Run: `cd /home/digitalghost/projects/aether && .venv/bin/pytest -v`
Expected: ALL PASS

- [ ] **Step 10: Commit**

```bash
cd /home/digitalghost/projects/aether
git add src/aether/lighting/zones.py tests/test_zones.py tests/test_mixer.py tests/test_focus.py tests/test_dj.py
git commit -m "refactor: expand ZONE_NAMES to 7, refactor ZoneManager for multi-adapter routing"
```

---

### Task 3: Implement OpenRGBAdapter

**Files:**
- Create: `src/aether/adapters/openrgb.py`
- Create: `tests/test_openrgb_adapter.py`

- [ ] **Step 1: Write failing tests for OpenRGBAdapter**

Create `tests/test_openrgb_adapter.py`:

```python
import json
from unittest.mock import MagicMock, patch, PropertyMock
from aether.adapters.openrgb import OpenRGBAdapter


def _make_fake_device(name: str):
    device = MagicMock()
    device.name = name
    device.modes = [MagicMock(name="Direct", id=0)]
    return device


def _make_fake_client(devices: list):
    client = MagicMock()
    client.devices = devices
    client.ee = MagicMock()
    return client


def test_publish_zone_sets_color_on_devices():
    dev1 = _make_fake_device("SteelSeries Apex 3 TKL")
    dev2 = _make_fake_device("SteelSeries Rival 600")
    client = _make_fake_client([dev1, dev2])
    mqtt = MagicMock()

    zones_config = {
        "desk": MagicMock(openrgb_devices=["SteelSeries Apex 3 TKL", "SteelSeries Rival 600"]),
    }

    with patch("aether.adapters.openrgb.OpenRGBClient", return_value=client):
        adapter = OpenRGBAdapter(mqtt, zones_config)
        adapter.connect()
        adapter.publish_zone("desk", {"r": 255, "g": 223, "b": 191, "brightness": 80})

    # Brightness 80% of (255, 223, 191) = (204, 178, 152)
    for dev in [dev1, dev2]:
        dev.set_color.assert_called_once()
        color_arg = dev.set_color.call_args[0][0]
        assert color_arg.red == 204
        assert color_arg.green == 178
        assert color_arg.blue == 152


def test_publish_zone_publishes_mqtt_status():
    dev1 = _make_fake_device("Keyboard")
    client = _make_fake_client([dev1])
    mqtt = MagicMock()

    zones_config = {
        "desk": MagicMock(openrgb_devices=["Keyboard"]),
    }

    with patch("aether.adapters.openrgb.OpenRGBClient", return_value=client):
        adapter = OpenRGBAdapter(mqtt, zones_config, topic_prefix="aether")
        adapter.connect()
        mqtt.publish.reset_mock()  # clear connect() status publishes
        adapter.publish_zone("desk", {"r": 255, "g": 0, "b": 0, "brightness": 100})

    mqtt.publish.assert_called_once()
    topic = mqtt.publish.call_args[0][0]
    assert topic == "aether/peripheral/zone/desk"


def test_publish_zone_skips_unconfigured_zone():
    client = _make_fake_client([])
    mqtt = MagicMock()
    zones_config = {}

    with patch("aether.adapters.openrgb.OpenRGBClient", return_value=client):
        adapter = OpenRGBAdapter(mqtt, zones_config)
        adapter.connect()
        adapter.publish_zone("desk", {"r": 255, "g": 0, "b": 0, "brightness": 100})

    mqtt.publish.assert_not_called()


def test_publish_zone_skips_missing_device():
    client = _make_fake_client([])  # no devices on server
    mqtt = MagicMock()

    zones_config = {
        "desk": MagicMock(openrgb_devices=["Missing Device"]),
    }

    with patch("aether.adapters.openrgb.OpenRGBClient", return_value=client):
        adapter = OpenRGBAdapter(mqtt, zones_config)
        adapter.connect()
        adapter.publish_zone("desk", {"r": 255, "g": 0, "b": 0, "brightness": 100})

    # Should not raise, just skip


def test_brightness_zero_sends_black():
    dev = _make_fake_device("Keyboard")
    client = _make_fake_client([dev])
    mqtt = MagicMock()

    zones_config = {
        "desk": MagicMock(openrgb_devices=["Keyboard"]),
    }

    with patch("aether.adapters.openrgb.OpenRGBClient", return_value=client):
        adapter = OpenRGBAdapter(mqtt, zones_config)
        adapter.connect()
        adapter.publish_zone("desk", {"r": 255, "g": 128, "b": 64, "brightness": 0})

    color_arg = dev.set_color.call_args[0][0]
    assert color_arg.red == 0
    assert color_arg.green == 0
    assert color_arg.blue == 0


def test_disconnect_not_connected():
    mqtt = MagicMock()
    adapter = OpenRGBAdapter(mqtt, {})
    adapter.disconnect()  # should not raise


def test_status_connected():
    dev = _make_fake_device("Keyboard")
    client = _make_fake_client([dev])
    mqtt = MagicMock()

    zones_config = {
        "desk": MagicMock(openrgb_devices=["Keyboard"]),
    }

    with patch("aether.adapters.openrgb.OpenRGBClient", return_value=client):
        adapter = OpenRGBAdapter(mqtt, zones_config, topic_prefix="aether")
        adapter.connect()

    # Check status was published
    status_calls = [c for c in mqtt.publish.call_args_list if "peripheral/status" in str(c)]
    assert len(status_calls) >= 1


def test_status_degraded_when_device_missing():
    client = _make_fake_client([])  # server has no devices
    mqtt = MagicMock()

    zones_config = {
        "desk": MagicMock(openrgb_devices=["Missing Keyboard"]),
    }

    with patch("aether.adapters.openrgb.OpenRGBClient", return_value=client):
        adapter = OpenRGBAdapter(mqtt, zones_config, topic_prefix="aether")
        adapter.connect()

    status_calls = [c for c in mqtt.publish.call_args_list if "peripheral/status" in str(c)]
    assert any('"degraded"' in str(c) for c in status_calls)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/digitalghost/projects/aether && .venv/bin/pytest tests/test_openrgb_adapter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aether.adapters.openrgb'`

- [ ] **Step 3: Implement OpenRGBAdapter**

Create `src/aether/adapters/openrgb.py`:

```python
from __future__ import annotations

import json
import logging
import sys
from typing import Any

try:
    from openrgb import OpenRGBClient
    from openrgb.utils import RGBColor
    HAS_OPENRGB = True
except ImportError:
    HAS_OPENRGB = False
    OpenRGBClient = None
    RGBColor = None

log = logging.getLogger(__name__)


class OpenRGBAdapter:
    def __init__(
        self,
        mqtt_client,
        zones_config: dict,
        host: str = "localhost",
        port: int = 6820,
        topic_prefix: str = "aether",
    ):
        self._mqtt = mqtt_client
        self._zones = zones_config
        self._host = host
        self._port = port
        self._prefix = topic_prefix
        self._client: Any | None = None
        self._device_map: dict[str, list] = {}  # zone_name -> [device objects]
        self._connected = False

    def connect(self) -> None:
        if not HAS_OPENRGB:
            print(
                "[aether] openrgb-python not installed — OpenRGB adapter disabled",
                file=sys.stderr,
            )
            return

        try:
            self._client = OpenRGBClient(self._host, self._port, name="aether")
        except Exception as e:
            print(f"[aether] OpenRGB connection failed: {e}", file=sys.stderr)
            self._publish_status("disconnected")
            return

        self._connected = True
        self._map_devices()

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

        # Scale RGB by brightness (OpenRGB has no separate brightness channel)
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

        # Publish observability status to MQTT
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

    def _publish_status(self, status: str) -> None:
        self._mqtt.publish(
            f"{self._prefix}/peripheral/status",
            json.dumps(status),
            retain=True,
        )
```

- [ ] **Step 4: Run tests**

Run: `cd /home/digitalghost/projects/aether && .venv/bin/pytest tests/test_openrgb_adapter.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
cd /home/digitalghost/projects/aether
git add src/aether/adapters/openrgb.py tests/test_openrgb_adapter.py
git commit -m "feat: implement OpenRGBAdapter with brightness scaling and MQTT observability"
```

---

### Task 4: Update Mixer to Use Module-Level ZONE_NAMES

**Files:**
- Modify: `src/aether/mixer.py:36,66,75` (references to `ZoneManager.ZONE_NAMES`)

- [ ] **Step 1: Update mixer imports and references**

In `src/aether/mixer.py`, add import at the top:

```python
from aether.lighting.zones import ZONE_NAMES
```

Replace all references to `ZoneManager.ZONE_NAMES` with `ZONE_NAMES`:

Line 36 (`submit_all`):
```python
    def submit_all(self, source: str, color: ColorState, priority: int, ttl_sec: float | None = None) -> None:
        for zone in ZONE_NAMES:
            self.submit(source, zone, color, priority, ttl_sec)
```

Line 66 (`resolve`):
```python
    def resolve(self) -> None:
        if self._zones.paused:
            return
        for zone in ZONE_NAMES:
            color = self._resolve_zone(zone)
            if color is not None:
                if self._last_resolved.get(zone) != color:
                    self._last_resolved[zone] = color
                    self._zones.set_zone(zone, color)
```

Line 75 (`get_active_claims`):
```python
    def get_active_claims(self) -> dict[str, Claim]:
        result = {}
        for zone in ZONE_NAMES:
            claims = self._claims.get(zone, {})
            if claims:
                winner = min(claims.values(), key=lambda c: (c.priority, -c.created_at))
                result[zone] = winner
        return result
```

Remove the now-unused import of `ZoneManager` from the `from aether.lighting.zones import ZoneManager` line. The full imports section should be:

```python
from aether.lighting.ramp import ColorState
from aether.lighting.zones import ZONE_NAMES
```

- [ ] **Step 2: Run all tests**

Run: `cd /home/digitalghost/projects/aether && .venv/bin/pytest -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
cd /home/digitalghost/projects/aether
git add src/aether/mixer.py
git commit -m "refactor: use module-level ZONE_NAMES in mixer instead of ZoneManager class attr"
```

---

### Task 5: Add Desk/Tower Claims to FocusMode

**Files:**
- Modify: `src/aether/modes/focus.py:54-68,70-86,88-101`
- Modify: `tests/test_focus.py`

- [ ] **Step 1: Write failing test for focus desk/tower lighting**

In `tests/test_focus.py`, add:

```python
def test_apply_work_lighting_desk_warm_white():
    cfg = FocusConfig(
        work_min=1, short_break_min=1, long_break_min=1, cycles=2,
        desk_color=[255, 223, 191], desk_brightness=80, tower_brightness=10,
    )
    mx = FakeMixer()
    cancel = asyncio.Event()
    pause = asyncio.Event()
    mode = FocusMode(cfg, mx, cancel, pause)
    mode._apply_work_lighting(progress=0.5)
    desk_subs = [(s, z, c, p) for s, z, c, p in mx.submissions if z == "desk"]
    assert len(desk_subs) == 1
    assert desk_subs[0][2] == ColorState(r=255, g=223, b=191, brightness=80)
    assert desk_subs[0][3] == 1  # priority


def test_apply_work_lighting_tower_dim():
    cfg = FocusConfig(
        work_min=1, short_break_min=1, long_break_min=1, cycles=2,
        desk_color=[255, 223, 191], desk_brightness=80, tower_brightness=10,
    )
    mx = FakeMixer()
    cancel = asyncio.Event()
    pause = asyncio.Event()
    mode = FocusMode(cfg, mx, cancel, pause)
    mode._apply_work_lighting(progress=0.5)
    tower_subs = [(s, z, c, p) for s, z, c, p in mx.submissions if z == "tower"]
    assert len(tower_subs) == 1
    assert tower_subs[0][2].brightness == 10
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/digitalghost/projects/aether && .venv/bin/pytest tests/test_focus.py::test_apply_work_lighting_desk_warm_white tests/test_focus.py::test_apply_work_lighting_tower_dim -v`
Expected: FAIL — no desk/tower submissions found

- [ ] **Step 3: Add desk/tower claims to all focus lighting methods**

In `src/aether/modes/focus.py`, update `_apply_work_lighting` (add after the bedroom submit, before `resolve()`):

```python
    def _apply_work_lighting(self, progress: float) -> None:
        cfg = self._config
        self._mixer.submit(
            "focus", "monitor",
            ColorState(r=cfg.work_color[0], g=cfg.work_color[1], b=cfg.work_color[2], brightness=cfg.work_brightness),
            priority=1,
        )
        rope_br = self._rope_brightness(progress)
        rope_color = ColorState(r=180, g=140, b=60, brightness=rope_br)
        self._mixer.submit("focus", "wall_left", rope_color, priority=1)
        self._mixer.submit("focus", "wall_right", rope_color, priority=1)
        off = ColorState(r=0, g=0, b=0, brightness=0)
        self._mixer.submit("focus", "floor", off, priority=1)
        self._mixer.submit("focus", "bedroom", off, priority=1)
        desk = ColorState(r=cfg.desk_color[0], g=cfg.desk_color[1], b=cfg.desk_color[2], brightness=cfg.desk_brightness)
        self._mixer.submit("focus", "desk", desk, priority=1)
        tower = ColorState(r=0, g=0, b=0, brightness=cfg.tower_brightness)
        self._mixer.submit("focus", "tower", tower, priority=1)
        self._mixer.resolve()
```

Update `_apply_break_lighting` (add before `resolve()`):

```python
    def _apply_break_lighting(self) -> None:
        cfg = self._config
        self._mixer.submit(
            "focus", "monitor",
            ColorState(r=cfg.work_color[0], g=cfg.work_color[1], b=cfg.work_color[2], brightness=60),
            priority=1,
        )
        break_color = ColorState(
            r=cfg.break_color[0], g=cfg.break_color[1], b=cfg.break_color[2],
            brightness=cfg.break_brightness,
        )
        self._mixer.submit("focus", "wall_left", break_color, priority=1)
        self._mixer.submit("focus", "wall_right", break_color, priority=1)
        off = ColorState(r=0, g=0, b=0, brightness=0)
        self._mixer.submit("focus", "floor", off, priority=1)
        self._mixer.submit("focus", "bedroom", off, priority=1)
        desk = ColorState(r=cfg.desk_color[0], g=cfg.desk_color[1], b=cfg.desk_color[2], brightness=cfg.desk_brightness)
        self._mixer.submit("focus", "desk", desk, priority=1)
        tower = ColorState(r=0, g=0, b=0, brightness=cfg.tower_brightness)
        self._mixer.submit("focus", "tower", tower, priority=1)
        self._mixer.resolve()
```

Update `_apply_long_break_lighting` (add before `resolve()`):

```python
    def _apply_long_break_lighting(self) -> None:
        cfg = self._config
        self._mixer.submit(
            "focus", "monitor",
            ColorState(r=cfg.work_color[0], g=cfg.work_color[1], b=cfg.work_color[2], brightness=60),
            priority=1,
        )
        amber = ColorState(r=255, g=180, b=60, brightness=70)
        self._mixer.submit("focus", "wall_left", amber, priority=1)
        self._mixer.submit("focus", "wall_right", amber, priority=1)
        off = ColorState(r=0, g=0, b=0, brightness=0)
        self._mixer.submit("focus", "floor", off, priority=1)
        self._mixer.submit("focus", "bedroom", off, priority=1)
        desk = ColorState(r=cfg.desk_color[0], g=cfg.desk_color[1], b=cfg.desk_color[2], brightness=cfg.desk_brightness)
        self._mixer.submit("focus", "desk", desk, priority=1)
        tower = ColorState(r=0, g=0, b=0, brightness=cfg.tower_brightness)
        self._mixer.submit("focus", "tower", tower, priority=1)
        self._mixer.resolve()
```

- [ ] **Step 4: Run focus tests**

Run: `cd /home/digitalghost/projects/aether && .venv/bin/pytest tests/test_focus.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
cd /home/digitalghost/projects/aether
git add src/aether/modes/focus.py tests/test_focus.py
git commit -m "feat: add desk (warm white) and tower (dim) claims to FocusMode"
```

---

### Task 6: Add Desk/Tower Claims to DJMode (Party)

**Files:**
- Modify: `src/aether/modes/dj.py:100-110`
- Modify: `tests/test_dj.py`

- [ ] **Step 1: Write failing test for party tower beat-sync**

In `tests/test_dj.py`, add:

```python
def test_apply_base_color_includes_tower():
    cfg = PartyConfig(
        palette=[[180, 50, 255]],
        tower_beat_sync=True,
        desk_accent=True,
    )
    mx = FakeMixer()
    mode = DJMode.__new__(DJMode)
    mode._config = cfg
    mode._mixer = mx
    mode._apply_base_color(180, 50, 255, brightness=80)
    tower_subs = [(s, z, c, p) for s, z, c, p in mx.submissions if z == "tower"]
    assert len(tower_subs) == 1
    assert tower_subs[0][2] == ColorState(r=180, g=50, b=255, brightness=80)


def test_apply_base_color_includes_desk_accent():
    cfg = PartyConfig(
        palette=[[180, 50, 255]],
        tower_beat_sync=True,
        desk_accent=True,
    )
    mx = FakeMixer()
    mode = DJMode.__new__(DJMode)
    mode._config = cfg
    mode._mixer = mx
    mode._apply_base_color(180, 50, 255, brightness=80)
    desk_subs = [(s, z, c, p) for s, z, c, p in mx.submissions if z == "desk"]
    assert len(desk_subs) == 1
    assert desk_subs[0][2] == ColorState(r=180, g=50, b=255, brightness=80)


def test_apply_accent_syncs_tower_when_enabled():
    cfg = PartyConfig(
        accent_zone="floor",
        accent_brightness_high=100,
        palette=[[255, 0, 0]],
        tower_beat_sync=True,
    )
    mx = FakeMixer()
    mode = DJMode.__new__(DJMode)
    mode._config = cfg
    mode._mixer = mx
    mode._current_base_color = (255, 0, 0)
    mode._apply_accent(100)
    tower_subs = [(s, z, c, p) for s, z, c, p in mx.submissions if z == "tower"]
    assert len(tower_subs) == 1
    assert tower_subs[0][2].brightness == 100
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/digitalghost/projects/aether && .venv/bin/pytest tests/test_dj.py::test_apply_base_color_includes_tower tests/test_dj.py::test_apply_accent_syncs_tower_when_enabled -v`
Expected: FAIL — no tower/desk submissions

- [ ] **Step 3: Update DJMode lighting methods**

In `src/aether/modes/dj.py`, update `_apply_base_color` (line 100):

```python
    def _apply_base_color(self, r: int, g: int, b: int, brightness: int = 80) -> None:
        color = ColorState(r=r, g=g, b=b, brightness=brightness)
        for zone in ("wall_left", "wall_right", "monitor", "bedroom"):
            self._mixer.submit("party", zone, color, priority=1)
        if self._config.desk_accent:
            self._mixer.submit("party", "desk", color, priority=1)
        if self._config.tower_beat_sync:
            self._mixer.submit("party", "tower", color, priority=1)
        self._mixer.resolve()
```

Update `_apply_accent` (line 106):

```python
    def _apply_accent(self, brightness: int) -> None:
        r, g, b = self._current_base_color
        accent = ColorState(r=r, g=g, b=b, brightness=brightness)
        self._mixer.submit("party", self._config.accent_zone, accent, priority=1)
        if self._config.tower_beat_sync:
            self._mixer.submit("party", "tower", accent, priority=1)
        self._mixer.resolve()
```

- [ ] **Step 4: Run DJ tests**

Run: `cd /home/digitalghost/projects/aether && .venv/bin/pytest tests/test_dj.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
cd /home/digitalghost/projects/aether
git add src/aether/modes/dj.py tests/test_dj.py
git commit -m "feat: add tower beat-sync and desk accent claims to DJMode"
```

---

### Task 7: Wire OpenRGB Into Daemon Startup

**Files:**
- Modify: `src/aether/cli.py:45-50` (adapter/zone init)

- [ ] **Step 1: Update daemon startup to build adapter routing dict**

In `src/aether/cli.py`, replace the adapter/zone/mixer initialization (lines 47-50):

```python
async def _run_daemon(config):
    loop = asyncio.get_running_loop()
    mqtt = MqttClient(broker=config.mqtt.broker, port=config.mqtt.port)
    govee_adapter = GoveeAdapter(mqtt, config.zones, topic_prefix=config.mqtt.topic_prefix)

    # Build adapter routing: zone_name → adapter instance
    adapters: dict = {}
    for zone_name, zone_cfg in config.zones.items():
        if zone_cfg.govee_device is not None:
            adapters[zone_name] = govee_adapter
    # For zones not in config but in ZONE_NAMES, they'll be skipped (no adapter)

    # OpenRGB adapter (optional)
    openrgb_adapter = None
    if config.openrgb.enabled:
        from aether.adapters.openrgb import OpenRGBAdapter

        openrgb_adapter = OpenRGBAdapter(
            mqtt, config.zones,
            host=config.openrgb.host,
            port=config.openrgb.port,
            topic_prefix=config.mqtt.topic_prefix,
        )
        openrgb_adapter.connect()
        for zone_name, zone_cfg in config.zones.items():
            if zone_cfg.openrgb_devices:
                adapters[zone_name] = openrgb_adapter

    zones = ZoneManager(adapters)
    mixer = Mixer(zones)
```

Also update the `adapter` reference used later in the file. The `GoveeAdapter` is still used directly for `publish_state`, `publish_transition`, `publish_presence`. Rename the variable from `adapter` to `govee_adapter` where it's used in handle_transition and sentry:

Line 148-149: `adapter.publish_state` → `govee_adapter.publish_state`
Line 149: `adapter.publish_transition` → `govee_adapter.publish_transition`

Line 107-112 (SentryAlert): `adapter=adapter` → `adapter=govee_adapter`

Line 218: `adapter.publish_presence` → `govee_adapter.publish_presence`

Add cleanup in the finally block (line 291):

```python
    finally:
        _stop_active_mode()
        camera.release()
        if openrgb_adapter is not None:
            openrgb_adapter.disconnect()
        mqtt.disconnect()
```

- [ ] **Step 2: Update `discover` command zone list**

In `src/aether/cli.py`, the `discover` command (around line 554) has a hardcoded zone list. Update it to only show Govee-eligible zones (OpenRGB devices are discovered via `openrgb --list-devices`):

```python
    zone_names = ["wall_left", "wall_right", "monitor", "floor", "bedroom"]
```

This stays as-is — `discover` is Govee-specific. No change needed.

- [ ] **Step 3: Run all tests to verify nothing broke**

Run: `cd /home/digitalghost/projects/aether && .venv/bin/pytest -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
cd /home/digitalghost/projects/aether
git add src/aether/cli.py
git commit -m "feat: wire OpenRGB adapter into daemon startup with multi-adapter routing"
```

---

### Task 8: Update Config Files and Dependencies

**Files:**
- Modify: `pyproject.toml`
- Modify: `config.example.yaml`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add openrgb-python to optional dependencies**

In `pyproject.toml`, add an `openrgb` optional dependency group:

```toml
[project.optional-dependencies]
dev = [
    "pytest",
    "pytest-asyncio",
]
openrgb = [
    "openrgb-python",
]
```

- [ ] **Step 2: Read and update config.example.yaml**

Read the current `config.example.yaml`, then add the `openrgb` section and desk/tower zones at the end of the `zones` section:

Add to `config.example.yaml`:

```yaml
# OpenRGB desk peripherals (optional — requires openrgb-python and OpenRGB server)
openrgb:
  enabled: false
  host: "localhost"
  port: 6820

# Under zones, add:
  # desk:
  #   openrgb_devices:
  #     - "SteelSeries Apex 3 TKL"
  #     - "SteelSeries Rival 600"
  # tower:
  #   openrgb_devices:
  #     - "Corsair Lighting Node"
  #     - "XPG RAM"
```

- [ ] **Step 3: Update CLAUDE.md**

Add to tech stack: `- **openrgb-python** (optional) — OpenRGB SDK client for desk peripherals`

Add to external dependencies: `- **OpenRGB** — RGB peripheral controller (`systemctl --user start openrgb-server`)`

Update architecture line to include: `+ OpenRGBAdapter → OpenRGB Server → USB peripherals`

Add to design specs: `- \`docs/superpowers/specs/2026-03-28-aether-phase3-peripherals-design.md\` — Phase 3 Peripherals (OpenRGB)`

- [ ] **Step 4: Commit**

```bash
cd /home/digitalghost/projects/aether
git add pyproject.toml config.example.yaml CLAUDE.md
git commit -m "docs: update config, deps, and CLAUDE.md for OpenRGB peripherals"
```

---

### Task 9: Final Integration Test (Manual)

**Files:** None (manual verification)

- [ ] **Step 1: Install OpenRGB**

```bash
paru -S openrgb
```

- [ ] **Step 2: Set up udev rules and start server**

```bash
sudo udevadm control --reload-rules && sudo udevadm trigger
```

Create `~/.config/systemd/user/openrgb-server.service`:

```ini
[Unit]
Description=OpenRGB SDK Server
After=default.target

[Service]
ExecStart=/usr/bin/openrgb --server --noautoconnect
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now openrgb-server
```

- [ ] **Step 3: Discover device names**

```bash
openrgb --list-devices
```

Note exact device names and update `~/.config/aether/config.yaml` with correct names under `desk` and `tower` zones. Also set `openrgb.enabled: true`.

- [ ] **Step 4: Install openrgb-python**

```bash
cd /home/digitalghost/projects/aether && .venv/bin/pip install openrgb-python
```

- [ ] **Step 5: Run daemon and verify**

```bash
cd /home/digitalghost/projects/aether && .venv/bin/python -m aether run --config ~/.config/aether/config.yaml
```

Verify:
- Desk peripherals (keyboard + mouse) follow circadian color
- Tower (case + RAM) follows circadian color
- `aether focus` → desk goes warm white, tower dims
- `aether focus-stop` → both return to circadian
- `aether party` (with music playing) → tower beat-syncs, desk shows accent
- `aether party-stop` → both return to circadian
- `aether sleep` → both cascade off
- MQTT topics `aether/peripheral/zone/desk` and `aether/peripheral/zone/tower` update correctly
- `aether/peripheral/status` shows "connected"

- [ ] **Step 6: Commit any config/fix adjustments from testing**

```bash
cd /home/digitalghost/projects/aether
git add -A
git commit -m "fix: adjustments from manual OpenRGB integration testing"
```
