# Aether Scene System — Per-Segment Multi-Color Lighting

**Date:** 2026-03-28
**Status:** Draft
**Depends on:** Phase 3 Peripherals (merged), Phase 3 Core (merged)

## Overview

Replace the circadian engine's single-color-per-phase palette with a **scene system** that defines per-zone, per-segment color gradients. Each time phase maps to a named scene. Users can override the active scene via voice or CLI, and reset to circadian defaults.

## Hardware Segment Counts

| Zone | Device | SKU | Segments | API |
|------|--------|-----|----------|-----|
| wall_left | Neon Rope #2 | H6641 | 22 (0-21) | Govee Platform API |
| wall_right | Neon Rope #1 | H6641 | 22 (0-21) | Govee Platform API |
| monitor | TV Backlight | H6168 | 15 (0-14) | Govee Platform API |
| floor | Floor Lamp | H6076 | 7 (0-6) | Govee Platform API |
| bedroom | Table Lamp | H6022 | 1 (single color) | Govee Platform API |
| desk | Apex 7 TKL | — | 1 (single color) | OpenRGB |
| tower | RAM/Case/Mobo/GPU | — | 1 (single color) | OpenRGB |

## Scene Data Model

A scene is a named collection of per-zone lighting definitions. Segmented zones use **color stops** with linear interpolation. Non-segmented zones use a single color.

```yaml
scenes:
  sunrise:
    wall_left:
      brightness: 70
      stops:
        - [0, [0, 220, 255]]       # bright cyan at start
        - [21, [0, 150, 180]]      # deeper teal at end
    wall_right:
      brightness: 70
      stops:
        - [0, [255, 160, 50]]      # warm amber
        - [21, [255, 120, 30]]     # deeper orange
    monitor:
      brightness: 70
      stops:
        - [0, [255, 160, 50]]
        - [14, [255, 120, 30]]
    floor:
      brightness: 80
      stops:
        - [0, [255, 255, 240]]     # warm white top
        - [6, [255, 200, 120]]     # amber base
    bedroom:
      color: [255, 255, 240]
      brightness: 60
    desk:
      color: [0, 200, 230]
      brightness: 70
    tower:
      color: [0, 180, 220]
      brightness: 50
```

### Interpolation

Given color stops, the engine computes per-segment RGB via linear interpolation:

- 1 stop: all segments get that color (solid)
- 2 stops: linear gradient across the segment range
- 3+ stops: piecewise linear gradient between adjacent stops

Stops reference segment indices. The engine interpolates between each pair of adjacent stops to compute the color for every segment in that range.

### Zones Without Scene Definitions

If a scene omits a zone, that zone is left unchanged (whatever the previous scene or mixer claim set). This allows partial scenes.

## Architecture

```
Circadian Engine (phase → scene name)
        │
        ▼
Scene Engine ──→ GoveeSegmentAdapter ──→ Govee Platform API (segmentedColorRgb)
     │
     └──→ Mixer ──→ ZoneManager ──→ OpenRGBAdapter (desk/tower single color)
                                 ──→ GoveeAdapter (MQTT observability)
```

### Scene Engine

**File:** `src/aether/scenes.py`

The scene engine:
1. Loads scene definitions from config
2. Computes per-segment colors from stops via interpolation
3. Sends segment commands to `GoveeSegmentAdapter` for Govee devices
4. Sends single-color commands to the mixer for OpenRGB zones (desk/tower)
5. Tracks the active scene and whether it's circadian-driven or manually overridden

```python
class SceneEngine:
    def __init__(self, config, segment_adapter, mixer):
        self._scenes: dict[str, Scene]  # parsed from config
        self._active_scene: str | None
        self._manual_override: bool = False  # True when user picks a scene

    async def apply_scene(self, name: str) -> None:
        # Compute segment colors, send to adapter and mixer

    async def apply_circadian_scene(self, phase: str) -> None:
        # Look up phase → scene name from config, apply if not manually overridden

    def reset_to_circadian(self) -> None:
        # Clear manual override, let circadian pick the scene

    def get_scene_names(self) -> list[str]:
        # List all available scenes
```

### GoveeSegmentAdapter

**File:** `src/aether/adapters/govee_segment.py`

Talks directly to the Govee Platform API v1 via HTTP for segment control. Separate from the existing `GoveeAdapter` (which handles MQTT).

```python
class GoveeSegmentAdapter:
    def __init__(self, api_key: str, rate_limit: float = 0.1):
        # httpx async client
        # Rate limiter: ~10 req/sec

    async def set_segments(self, device_id: str, sku: str,
                           segments: dict[int, tuple[int,int,int]],
                           brightness: int) -> None:
        # Groups segments by color to minimize API calls
        # Sends segmentedColorRgb commands to Govee Platform API

    async def set_color(self, device_id: str, sku: str,
                        color: tuple[int,int,int], brightness: int) -> None:
        # Single color for entire device (non-segmented fallback)

    async def set_brightness(self, device_id: str, sku: str,
                             brightness: int) -> None:
        # Set device brightness
```

**API endpoint:** `https://openapi.api.govee.com/router/api/v1/device/control`

**Payload format for segmentedColorRgb:**
```json
{
    "requestId": "uuid",
    "payload": {
        "sku": "H6641",
        "device": "10:BD:C9:F0:82:86:41:83",
        "capability": {
            "type": "devices.capabilities.segment_color_setting",
            "instance": "segmentedColorRgb",
            "value": {
                "segment": [0, 1, 2, 3],
                "rgb": 14540031
            }
        }
    }
}
```

RGB is encoded as a single integer: `(r << 16) | (g << 8) | b`.

**Rate limiting:** Govee allows ~10 req/sec. Applying a scene across 4 segmented devices with gradients needs multiple calls per device (one per unique color group). Segments with the same interpolated color are batched into one call. Typical scene application: 2-4 seconds for all devices.

**API key:** Read from `GOVEE_API_KEY` env var or `govee.api_key` config field. Same key govee2mqtt uses.

### Coexistence with Existing Adapters

- **GoveeAdapter** (MQTT): Still used for state publishing, presence publishing, transition publishing, sentry alerts. Publishes the active scene's dominant color per zone for observability.
- **GoveeSegmentAdapter** (HTTP): Used exclusively by the scene engine for segment color control.
- **OpenRGBAdapter**: Receives single-color commands from the mixer for desk/tower zones. Scene engine submits these through the mixer at priority 2 (same as circadian).

## Circadian Integration

The `palettes:` config key is replaced by `phase_scenes:` which maps time phases to scene names.

```yaml
circadian:
  update_interval_sec: 30
  return_ramp_sec: 8
  phase_scenes:
    dawn: sunrise
    morning: sunrise
    midday: sunrise
    golden_hour: golden
    evening: purple_night
    night: purple_night
    nightlight: dim_amber
```

When the circadian engine ticks:
1. Compute current phase from sun times
2. Look up scene name from `phase_scenes`
3. If scene changed from last tick and no manual override active, call `scene_engine.apply_scene(name)`

**No cross-fade between scenes.** Phase transitions snap to the new scene. Transitions happen at natural lighting boundaries (dawn, dusk) where a snap is not jarring.

**AWAY state:** Applies the `nightlight` scene — a simple dim warm glow.

**Return ramp (AWAY → PRESENT):** Snaps to the current phase scene immediately. The existing 8-second compressed ramp is replaced by a scene apply.

## Mode Interaction

When a mode (FOCUS/PARTY/SLEEP) is active:
- The scene engine pauses scene application for Govee zones
- Modes control lighting through the mixer as before (single-color claims at priority 1)
- OpenRGB zones (desk/tower) still receive mode claims through the mixer
- When the mode exits, the scene engine re-applies the current scene

## Voice Commands

New intents added to `src/aether/vox/intent.py`:

| Command Pattern | Intent | Action |
|---|---|---|
| "set scene {name}" / "switch to {name}" | `SCENE_SET` | Apply named scene, pause circadian |
| "random scene" / "pick a scene" | `SCENE_RANDOM` | Apply random scene, pause circadian |
| "reset" / "go back to default" / "normal" | `SCENE_RESET` | Resume circadian phase mapping |
| "what scene" / "current scene" | `SCENE_QUERY` | Publish current scene name to MQTT |

Scene name extraction: The intent classifier matches "set scene" or "switch to" as a prefix, then uses the remaining text as the scene name. Fuzzy matching against available scene names (case-insensitive, partial match).

## CLI Commands

```bash
aether scene sunrise          # apply scene
aether scene --random         # random scene
aether scene --reset          # back to circadian
aether scene --list           # list available scenes
```

## MQTT Topics

```
aether/scene/active          # current scene name (retained)
aether/scene/mode            # "circadian" | "manual" (retained)
```

## Config Changes

### New Config Models

```python
class SceneZoneConfig(BaseModel):
    color: list[int] | None = None           # [r, g, b] for single-color zones
    brightness: int = 100
    stops: list[list] | None = None          # [[segment_idx, [r, g, b]], ...] for gradients
    # Parsed at load time: stops[i][0] = int segment index, stops[i][1] = [r, g, b]

class SceneConfig(BaseModel):
    zones: dict[str, SceneZoneConfig] = {}   # zone_name -> zone config

class GoveeApiConfig(BaseModel):
    api_key: str | None = None               # or read from GOVEE_API_KEY env var
```

### AetherConfig Changes

```python
class AetherConfig(BaseModel):
    # ... existing fields ...
    scenes: dict[str, SceneConfig] = {}      # scene_name -> scene definition
    govee_api: GoveeApiConfig = GoveeApiConfig()
```

### CircadianConfig Changes

```python
class CircadianConfig(BaseModel):
    update_interval_sec: int = 30
    return_ramp_sec: int = 8
    phase_scenes: dict[str, str] = {}        # phase_name -> scene_name
    # palettes: removed
```

## Scenes

### sunrise (daytime daily driver)

Recreated from user's Govee app preset. Cyan-teal left rope, warm amber right rope, warm monitor, white-to-amber floor lamp.

```yaml
sunrise:
  wall_left:
    brightness: 70
    stops:
      - [0, [0, 220, 255]]
      - [21, [0, 150, 180]]
  wall_right:
    brightness: 70
    stops:
      - [0, [255, 160, 50]]
      - [21, [255, 120, 30]]
  monitor:
    brightness: 70
    stops:
      - [0, [255, 160, 50]]
      - [14, [255, 120, 30]]
  floor:
    brightness: 80
    stops:
      - [0, [255, 255, 240]]
      - [6, [255, 200, 120]]
  bedroom:
    color: [255, 255, 240]
    brightness: 60
  desk:
    color: [0, 200, 230]
    brightness: 70
  tower:
    color: [0, 180, 220]
    brightness: 50
```

### purple_night (nighttime)

Recreated from user's nighttime setup. Uniform deep purple/violet across everything. Makes the blacklight tapestry pop.

```yaml
purple_night:
  wall_left:
    brightness: 70
    stops:
      - [0, [92, 0, 255]]
      - [21, [80, 0, 220]]
  wall_right:
    brightness: 70
    stops:
      - [0, [92, 0, 255]]
      - [21, [80, 0, 220]]
  monitor:
    brightness: 70
    stops:
      - [0, [80, 0, 220]]
      - [14, [60, 0, 200]]
  floor:
    brightness: 60
    stops:
      - [0, [92, 0, 255]]
      - [6, [60, 0, 180]]
  bedroom:
    color: [80, 0, 200]
    brightness: 40
  desk:
    color: [92, 0, 255]
    brightness: 60
  tower:
    color: [80, 0, 220]
    brightness: 50
```

### deep_space

Dark blue-black with scattered bright white accents — like stars. Sci-fi cockpit feel.

```yaml
deep_space:
  wall_left:
    brightness: 50
    stops:
      - [0, [5, 5, 40]]
      - [7, [200, 200, 255]]
      - [10, [5, 5, 40]]
      - [18, [150, 150, 220]]
      - [21, [5, 5, 40]]
  wall_right:
    brightness: 50
    stops:
      - [0, [5, 5, 40]]
      - [5, [150, 150, 220]]
      - [8, [5, 5, 40]]
      - [15, [200, 200, 255]]
      - [21, [5, 5, 40]]
  monitor:
    brightness: 40
    stops:
      - [0, [10, 10, 60]]
      - [14, [5, 5, 40]]
  floor:
    brightness: 40
    stops:
      - [0, [180, 180, 255]]
      - [3, [10, 10, 50]]
      - [6, [5, 5, 40]]
  bedroom:
    color: [10, 10, 50]
    brightness: 20
  desk:
    color: [20, 20, 80]
    brightness: 40
  tower:
    color: [10, 10, 60]
    brightness: 30
```

### ember

Dying fire. Deep reds and oranges. Cozy and warm.

```yaml
ember:
  wall_left:
    brightness: 60
    stops:
      - [0, [180, 30, 0]]
      - [10, [255, 120, 20]]
      - [21, [120, 20, 0]]
  wall_right:
    brightness: 60
    stops:
      - [0, [120, 20, 0]]
      - [10, [255, 100, 10]]
      - [21, [180, 30, 0]]
  monitor:
    brightness: 50
    stops:
      - [0, [255, 100, 10]]
      - [14, [180, 50, 0]]
  floor:
    brightness: 60
    stops:
      - [0, [255, 140, 30]]
      - [3, [255, 80, 10]]
      - [6, [120, 20, 0]]
  bedroom:
    color: [200, 60, 10]
    brightness: 30
  desk:
    color: [180, 40, 0]
    brightness: 50
  tower:
    color: [120, 20, 0]
    brightness: 40
```

### forest

Greens and teals. Natural, calming.

```yaml
forest:
  wall_left:
    brightness: 60
    stops:
      - [0, [0, 180, 80]]
      - [10, [80, 220, 40]]
      - [21, [0, 150, 60]]
  wall_right:
    brightness: 60
    stops:
      - [0, [0, 160, 130]]
      - [10, [0, 200, 100]]
      - [21, [0, 140, 80]]
  monitor:
    brightness: 50
    stops:
      - [0, [40, 180, 80]]
      - [14, [20, 140, 60]]
  floor:
    brightness: 60
    stops:
      - [0, [80, 200, 60]]
      - [3, [40, 160, 80]]
      - [6, [200, 160, 60]]
  bedroom:
    color: [40, 140, 60]
    brightness: 30
  desk:
    color: [0, 180, 80]
    brightness: 50
  tower:
    color: [0, 120, 60]
    brightness: 40
```

### neon_tokyo

Cyberpunk. Hot pink and electric blue.

```yaml
neon_tokyo:
  wall_left:
    brightness: 80
    stops:
      - [0, [255, 20, 100]]
      - [10, [180, 0, 200]]
      - [21, [0, 100, 255]]
  wall_right:
    brightness: 80
    stops:
      - [0, [0, 100, 255]]
      - [10, [180, 0, 200]]
      - [21, [255, 20, 100]]
  monitor:
    brightness: 70
    stops:
      - [0, [255, 0, 120]]
      - [14, [200, 0, 180]]
  floor:
    brightness: 70
    stops:
      - [0, [255, 20, 100]]
      - [3, [200, 0, 200]]
      - [6, [0, 80, 255]]
  bedroom:
    color: [200, 0, 180]
    brightness: 50
  desk:
    color: [255, 20, 100]
    brightness: 70
  tower:
    color: [0, 80, 255]
    brightness: 60
```

### golden

Warm monochrome. Elegant, rich.

```yaml
golden:
  wall_left:
    brightness: 70
    stops:
      - [0, [255, 200, 50]]
      - [21, [255, 160, 30]]
  wall_right:
    brightness: 70
    stops:
      - [0, [255, 180, 40]]
      - [21, [255, 140, 20]]
  monitor:
    brightness: 60
    stops:
      - [0, [255, 190, 40]]
      - [14, [255, 150, 20]]
  floor:
    brightness: 70
    stops:
      - [0, [255, 220, 80]]
      - [6, [255, 160, 30]]
  bedroom:
    color: [255, 180, 40]
    brightness: 40
  desk:
    color: [255, 200, 60]
    brightness: 60
  tower:
    color: [255, 160, 30]
    brightness: 50
```

### arctic

Cool whites and icy blues. Clean, focused.

```yaml
arctic:
  wall_left:
    brightness: 80
    stops:
      - [0, [220, 240, 255]]
      - [21, [150, 200, 255]]
  wall_right:
    brightness: 80
    stops:
      - [0, [200, 230, 255]]
      - [21, [140, 190, 255]]
  monitor:
    brightness: 70
    stops:
      - [0, [200, 220, 255]]
      - [14, [160, 200, 255]]
  floor:
    brightness: 80
    stops:
      - [0, [240, 250, 255]]
      - [6, [180, 210, 255]]
  bedroom:
    color: [200, 220, 255]
    brightness: 50
  desk:
    color: [220, 240, 255]
    brightness: 70
  tower:
    color: [180, 210, 255]
    brightness: 50
```

### dim_amber (nightlight — AWAY state)

Simple dim warm glow. No gradients needed.

```yaml
dim_amber:
  wall_left:
    color: [180, 140, 60]
    brightness: 5
  wall_right:
    color: [180, 140, 60]
    brightness: 5
  monitor:
    color: [180, 140, 60]
    brightness: 5
  floor:
    color: [180, 140, 60]
    brightness: 5
  bedroom:
    color: [180, 140, 60]
    brightness: 5
  desk:
    color: [180, 140, 60]
    brightness: 5
  tower:
    color: [0, 0, 0]
    brightness: 0
```

## Error Handling

| Failure | Behavior |
|---------|----------|
| Govee API key missing | Scene engine logs warning, falls back to existing single-color circadian path |
| Govee API rate limited (429) | Retry with backoff, skip remaining segments if persistent |
| Govee API unreachable | Log error, OpenRGB zones still update via mixer |
| Scene name not found | Log warning, ignore command |
| Scene missing a zone | Leave that zone unchanged |
| Mode active during scene apply | Skip Govee zones, only apply OpenRGB zones via mixer |

## Testing Strategy

- **Unit tests:** Scene interpolation (1 stop, 2 stops, 3+ stops), scene loading from config, phase-to-scene mapping, intent matching for scene commands
- **GoveeSegmentAdapter tests:** Mock httpx, verify API payload format (segment arrays, RGB encoding), rate limiting
- **Integration tests (manual):** Apply scenes, verify segment colors on physical devices, test voice commands, test circadian phase transitions

## Deferred

- Cross-fade transitions between scenes
- Per-segment animation (breathing, color cycling along segments)
- Scene editor UI
- Importing Govee DIY scenes
- Per-segment control in FOCUS/PARTY/SLEEP modes
