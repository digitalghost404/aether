# Aether Phase 3 Peripherals — OpenRGB Desk Lighting

**Date:** 2026-03-28
**Status:** Draft
**Depends on:** Phase 3 Core (merged)

## Overview

Extend Aether's lighting control to desk peripherals (keyboard, mouse, case LEDs, RAM) via OpenRGB. Two new zones (`desk`, `tower`) integrate into the existing mixer/zone architecture so circadian, modes, and manual overrides work across all 7 zones without special-casing.

## Hardware

| Zone | Devices |
|------|---------|
| `desk` | SteelSeries Apex 3 TKL (keyboard), SteelSeries Rival 600 (mouse) |
| `tower` | Corsair case lighting, XPG RAM (4 sticks) |

All devices treated as single-color per device (no per-key or per-stick zones in v1).

## Architecture

```
Mixer ──submit_all()──→ ZoneManager ──set_zone()──→ GoveeAdapter ──→ MQTT ──→ govee2mqtt
                                     ──set_zone()──→ OpenRGBAdapter ──→ OpenRGB Server ──→ USB Devices
                                                     └── publish status → MQTT (observability only)
```

### Zone Routing

ZoneManager receives a `dict[str, adapter]` mapping each zone name to its adapter. `set_zone()` looks up the adapter for the given zone and calls `publish_zone()` on it. The 5 existing Govee zones route to `GoveeAdapter`, the 2 new zones route to `OpenRGBAdapter`.

`ZONE_NAMES` expands from 5 to 7 as a constant:

```python
ZONE_NAMES = ("wall_left", "wall_right", "monitor", "floor", "bedroom", "desk", "tower")
```

### Mixer Impact

None. The mixer already submits claims by zone name. `submit_all()` iterates `ZONE_NAMES`, so new zones get claims automatically.

### CircadianEngine Impact

None. Already uses `mixer.submit_all()` at priority 2. New zones receive circadian colors for free.

## OpenRGBAdapter

**File:** `src/aether/adapters/openrgb.py`

**Dependencies:** `openrgb-python` (PyPI)

### Interface

```python
class OpenRGBAdapter:
    def __init__(self, mqtt_client, zones_config: dict, host: str = "localhost", port: int = 6820)
    def connect(self) -> None          # Connect to OpenRGB server with retries
    def disconnect(self) -> None       # Clean shutdown, turn devices off
    def publish_zone(self, zone: str, color: ColorState) -> None  # Set zone color + MQTT status
```

### Connection Lifecycle

- Connects to OpenRGB server at daemon startup via `openrgb-python` SDK (TCP socket, default port 6820).
- 3 retries with exponential backoff (2s, 4s, 8s).
- If connection fails, adapter disables itself. Daemon continues with Govee zones only.
- Background reconnect task every 30s if connection is lost mid-session.
- On reconnect, `flush_current()` re-publishes current zone state to devices.

### Device Matching

Devices are matched by name string from config against `device.name` from the OpenRGB server. If a configured device is not found (USB unplugged, etc.), it is skipped with a warning log. Other devices in the same zone still receive updates.

### Brightness Handling

OpenRGB has no separate brightness channel — it's RGB only. Brightness is applied by scaling RGB values:

```python
actual_r = color.r * color.brightness // 100
actual_g = color.g * color.brightness // 100
actual_b = color.b * color.brightness // 100
```

This keeps `ColorState` universal across both adapters.

### Color Application

For each device in the zone:
1. Set mode to "Direct" (immediate control, bypasses device firmware effects).
2. Set all LEDs on the device to the same `RGBColor(r, g, b)`.

Per-zone keyboard lighting (Apex 3 TKL has 10 zones) and per-stick RAM control are deferred to a future version.

## ZoneManager Changes

**File:** `src/aether/lighting/zones.py`

### Before

```python
class ZoneManager:
    def __init__(self, govee_adapter):
        self._adapter = govee_adapter
```

### After

```python
class ZoneManager:
    def __init__(self, adapters: dict[str, Any]):
        self._adapters = adapters  # zone_name → adapter instance

    def set_zone(self, zone: str, state: ColorState) -> None:
        # Existing dedup + pause logic unchanged
        adapter = self._adapters.get(zone)
        if adapter is not None:
            adapter.publish_zone(zone, state)
```

`set_all()` and `flush_current()` iterate `self._adapters` instead of calling a single adapter.

## Config Changes

**File:** `src/aether/config.py`

### New Pydantic Models

```python
class OpenRGBConfig(BaseModel):
    enabled: bool = True
    host: str = "localhost"
    port: int = 6820
    retry_attempts: int = 3
    retry_delay_sec: float = 2.0
```

### ZoneConfig Extension

```python
class ZoneConfig(BaseModel):
    govee_device: str | None = None
    openrgb_devices: list[str] | None = None
```

A zone has either `govee_device` or `openrgb_devices`, never both. The populated field determines which adapter owns the zone.

### AetherConfig Addition

```python
class AetherConfig(BaseModel):
    # ... existing fields ...
    openrgb: OpenRGBConfig = OpenRGBConfig()
```

### Example Config (new zones)

```yaml
openrgb:
  enabled: true
  host: "localhost"
  port: 6820

zones:
  wall_left:
    govee_device: "10BDC9F082864183"
  wall_right:
    govee_device: "1726C9F083C63131"
  monitor:
    govee_device: "366BD4ADFCCCCE28"
  floor:
    govee_device: "F792D67D42861E43"
  bedroom:
    govee_device: "2DFBD40F4486074D"
  desk:
    openrgb_devices:
      - "SteelSeries Apex 3 TKL"
      - "SteelSeries Rival 600"
  tower:
    openrgb_devices:
      - "Corsair Lighting Node"
      - "XPG RAM"
```

Note: Exact device names come from `openrgb --list-devices` on the user's system. The names above are placeholders — actual names will be confirmed during setup. OpenRGB may expose RAM as 4 individual stick devices rather than one — if so, list all 4 under `tower.openrgb_devices`. The adapter sets them all to the same color regardless.

## Mode Behavior

### PRESENT (Circadian)

No changes. `submit_all()` covers all 7 zones. Desk and tower follow the room's circadian color.

### AWAY

No changes. `submit_all()` dims all zones to nightlight. Return ramp covers all zones.

### FOCUS

New claims at priority 1:
- `desk`: Fixed warm white `ColorState(255, 223, 191, 80)` (~4000K). Does not drift with circadian.
- `tower`: Dim `ColorState(0, 0, 0, 10)`. Reduces visual distraction.

Claims submitted on FOCUS entry, released on FOCUS exit (existing mode lifecycle).

### PARTY

New claims at priority 1:
- `tower`: Beat-sync claims from `dj.py` (same mechanism as wall zones). Receives accent color on beat events.
- `desk`: Base accent color (no beat-sync). Stays readable, not distracting.

### SLEEP

No changes. Cascade shutdown via `submit_all()` covers all zones. Desk and tower turn off with everything else.

## MQTT Topics

Read-only observability topics (no inbound commands):

```
aether/peripheral/zone/desk      # ColorState JSON: {"r", "g", "b", "brightness"}
aether/peripheral/zone/tower     # ColorState JSON
aether/peripheral/status         # "connected" | "disconnected" | "degraded"
aether/peripheral/devices        # JSON array of connected device names
```

`degraded` = connected to OpenRGB server but one or more configured devices are missing.

## Error Handling & Graceful Degradation

| Failure | Behavior |
|---------|----------|
| OpenRGB server not running at startup | Adapter disables itself, logs warning. Govee zones work normally. Mixer still submits claims to desk/tower but ZoneManager skips (adapter is None). |
| OpenRGB server crashes mid-session | `publish_zone()` catches `ConnectionError`, logs it, marks adapter disconnected. Background task retries every 30s. On reconnect, flushes current state. |
| USB device unplugged | OpenRGB SDK error on specific device. Adapter skips that device, logs warning. Other devices in zone still update. Device re-mapped on next successful query. |
| `openrgb-python` not installed | Import guarded. Adapter class unavailable. Config validation warns if `openrgb.enabled` is true but package is missing. |

## External Dependencies

### OpenRGB Server (systemd user service)

```ini
# ~/.config/systemd/user/openrgb-server.service
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

### Startup Chain

```
systemctl start mosquitto           # MQTT broker (system service)
docker compose up -d govee2mqtt     # Govee bridge (Docker)
systemctl --user start openrgb-server  # OpenRGB SDK server (user service)
aether run                          # Daemon connects to all three
```

### Python Dependencies

- `openrgb-python` — OpenRGB SDK client (PyPI)
- No other new dependencies

## Testing Strategy

- **Unit tests:** Mock `openrgb-python` client. Test adapter color scaling, device matching, zone routing, reconnect logic.
- **ZoneManager tests:** Update existing tests to use adapter dict instead of single adapter. Add tests for mixed Govee + OpenRGB routing.
- **Mixer tests:** No changes needed — mixer is adapter-unaware.
- **Mode tests:** Add assertions that FOCUS/PARTY submit correct claims for desk/tower zones.
- **Integration test (manual):** Run daemon with OpenRGB server and verify devices change color on state transitions.

## Deferred

- Per-key keyboard zones (Apex 3 TKL has 10 zones)
- Per-stick RAM color (4 independent sticks)
- OpenRGB inbound MQTT commands (set desk color via MQTT)
- Auto-discovery of devices to zones
- OpenRGB profile save/restore
