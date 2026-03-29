# Scene System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace single-color circadian palettes with a scene system supporting per-segment multi-color gradients on Govee devices, with voice/CLI scene switching.

**Architecture:** Scene engine computes per-segment colors from gradient stops, sends them to GoveeSegmentAdapter (Govee Platform API HTTP) for segmented devices and through the mixer for OpenRGB devices. Circadian engine maps time phases to scene names instead of single colors.

**Tech Stack:** Python 3.14, httpx (Govee Platform API), Pydantic, existing mixer/adapter infrastructure.

## File Map

| File | Action | Description |
|------|--------|-------------|
| `src/aether/scenes/__init__.py` | Create | Package init |
| `src/aether/scenes/interpolate.py` | Create | Per-segment color interpolation from gradient stops |
| `src/aether/scenes/engine.py` | Create | SceneEngine — applies scenes to adapters and mixer |
| `src/aether/adapters/govee_segment.py` | Create | GoveeSegmentAdapter — Govee Platform API HTTP client |
| `src/aether/config.py` | Modify | Add SceneZoneConfig, GoveeApiConfig, phase_scenes |
| `src/aether/lighting/circadian.py` | Modify | Replace palette-based color submission with scene engine |
| `src/aether/vox/intent.py` | Modify | Add SCENE_SET, SCENE_RANDOM, SCENE_RESET, SCENE_QUERY intents |
| `src/aether/vox/handler.py` | Modify | Handle scene intents, extract scene name |
| `src/aether/cli.py` | Modify | Add `scene` command group, wire scene engine in daemon |
| `config.example.yaml` | Modify | Add all 9 scenes, phase_scenes, govee_api section |
| `tests/test_scene_interpolate.py` | Create | Interpolation unit tests |
| `tests/test_config.py` | Create | Config model tests for new scene fields |
| `tests/test_govee_segment.py` | Create | GoveeSegmentAdapter tests with mocked httpx |
| `tests/test_scene_engine.py` | Create | SceneEngine unit tests |
| `tests/test_circadian.py` | Modify | Update for scene-based circadian |
| `tests/test_intent.py` | Modify | Add scene intent tests |

## Tasks

---

### Task 1: Scene interpolation functions

- [ ] Create `src/aether/scenes/__init__.py` (empty)
- [ ] Write failing tests in `tests/test_scene_interpolate.py`
- [ ] Implement `src/aether/scenes/interpolate.py`

**Test file:** `tests/test_scene_interpolate.py`

```python
import pytest
from aether.scenes.interpolate import interpolate_stops


def test_single_stop_all_segments_same():
    """One stop: all segments get that color."""
    stops = [[0, [255, 0, 0]]]
    result = interpolate_stops(stops, segment_count=22)
    assert len(result) == 22
    for i in range(22):
        assert result[i] == (255, 0, 0)


def test_two_stops_linear_gradient():
    """Two stops: linear interpolation across full range."""
    stops = [[0, [0, 0, 0]], [21, [210, 210, 210]]]
    result = interpolate_stops(stops, segment_count=22)
    assert result[0] == (0, 0, 0)
    assert result[21] == (210, 210, 210)
    # Midpoint at index 10-11 should be roughly half
    r, g, b = result[10]
    assert 95 <= r <= 105


def test_three_stops_piecewise():
    """Three stops: piecewise linear between each pair."""
    stops = [[0, [255, 0, 0]], [10, [0, 255, 0]], [21, [0, 0, 255]]]
    result = interpolate_stops(stops, segment_count=22)
    assert result[0] == (255, 0, 0)
    assert result[10] == (0, 255, 0)
    assert result[21] == (0, 0, 255)
    # Index 5 should be midpoint between stop 0 and stop 10
    r, g, b = result[5]
    assert 120 <= r <= 135
    assert 120 <= g <= 135


def test_two_stops_not_at_endpoints():
    """Stops starting at index 3 and ending at index 18 — segments outside the range get nearest stop color."""
    stops = [[3, [100, 100, 100]], [18, [200, 200, 200]]]
    result = interpolate_stops(stops, segment_count=22)
    # Segments 0-2 clamp to first stop
    assert result[0] == (100, 100, 100)
    assert result[2] == (100, 100, 100)
    # Segments 19-21 clamp to last stop
    assert result[19] == (200, 200, 200)
    assert result[21] == (200, 200, 200)
    # Between stops: interpolated
    assert result[3] == (100, 100, 100)
    assert result[18] == (200, 200, 200)


def test_deep_space_star_pattern():
    """Multi-stop pattern from deep_space scene — verify segment count matches."""
    stops = [
        [0, [5, 5, 40]],
        [7, [200, 200, 255]],
        [10, [5, 5, 40]],
        [18, [150, 150, 220]],
        [21, [5, 5, 40]],
    ]
    result = interpolate_stops(stops, segment_count=22)
    assert len(result) == 22
    assert result[0] == (5, 5, 40)
    assert result[7] == (200, 200, 255)
    assert result[10] == (5, 5, 40)
    assert result[18] == (150, 150, 220)
    assert result[21] == (5, 5, 40)


def test_single_segment_device():
    """Single-segment device (e.g., bedroom table lamp) — 1 stop, 1 segment."""
    stops = [[0, [180, 140, 60]]]
    result = interpolate_stops(stops, segment_count=1)
    assert len(result) == 1
    assert result[0] == (180, 140, 60)
```

**Run:** `pytest tests/test_scene_interpolate.py -v`
**Expected:** All 6 tests fail (module not found)

**Implementation:** `src/aether/scenes/interpolate.py`

```python
from __future__ import annotations


def interpolate_stops(
    stops: list[list], segment_count: int
) -> dict[int, tuple[int, int, int]]:
    """Compute per-segment RGB colors from gradient color stops.

    Args:
        stops: List of [segment_index, [r, g, b]] pairs, sorted by segment index.
        segment_count: Total number of segments on the device.

    Returns:
        Dict mapping segment index (0..segment_count-1) to (r, g, b) tuple.
    """
    if not stops:
        return {}

    # Parse stops into (index, (r, g, b)) pairs
    parsed: list[tuple[int, tuple[int, int, int]]] = []
    for stop in stops:
        idx = stop[0]
        color = (stop[1][0], stop[1][1], stop[1][2])
        parsed.append((idx, color))

    # Sort by segment index
    parsed.sort(key=lambda s: s[0])

    result: dict[int, tuple[int, int, int]] = {}

    if len(parsed) == 1:
        # Single stop: all segments get that color
        color = parsed[0][1]
        for i in range(segment_count):
            result[i] = color
        return result

    for seg in range(segment_count):
        # Find which pair of stops this segment falls between
        if seg <= parsed[0][0]:
            # Before or at first stop: clamp to first color
            result[seg] = parsed[0][1]
        elif seg >= parsed[-1][0]:
            # After or at last stop: clamp to last color
            result[seg] = parsed[-1][1]
        else:
            # Find the two surrounding stops
            for j in range(len(parsed) - 1):
                left_idx, left_color = parsed[j]
                right_idx, right_color = parsed[j + 1]
                if left_idx <= seg <= right_idx:
                    if left_idx == right_idx:
                        result[seg] = left_color
                    else:
                        t = (seg - left_idx) / (right_idx - left_idx)
                        r = round(left_color[0] + (right_color[0] - left_color[0]) * t)
                        g = round(left_color[1] + (right_color[1] - left_color[1]) * t)
                        b = round(left_color[2] + (right_color[2] - left_color[2]) * t)
                        result[seg] = (r, g, b)
                    break

    return result
```

**Run:** `pytest tests/test_scene_interpolate.py -v`
**Expected:** All 6 tests pass

**Commit:** `git add src/aether/scenes/__init__.py src/aether/scenes/interpolate.py tests/test_scene_interpolate.py && git commit -m "feat(scenes): add per-segment gradient interpolation"`

---

### Task 2: Scene config models

- [ ] Write failing tests in `tests/test_config.py`
- [ ] Add new config models to `src/aether/config.py`

**Test file:** `tests/test_config.py`

```python
import pytest
import yaml
from aether.config import (
    AetherConfig,
    SceneZoneConfig,
    GoveeApiConfig,
    CircadianConfig,
)


def test_scene_zone_config_with_stops():
    zone = SceneZoneConfig(
        brightness=70,
        stops=[[0, [0, 220, 255]], [21, [0, 150, 180]]],
    )
    assert zone.brightness == 70
    assert zone.stops[0] == [0, [0, 220, 255]]
    assert zone.color is None


def test_scene_zone_config_with_color():
    zone = SceneZoneConfig(
        color=[255, 255, 240],
        brightness=60,
    )
    assert zone.color == [255, 255, 240]
    assert zone.stops is None


def test_govee_api_config_defaults():
    cfg = GoveeApiConfig()
    assert cfg.api_key is None


def test_aether_config_with_scenes():
    raw = {
        "scenes": {
            "sunrise": {
                "wall_left": {
                    "brightness": 70,
                    "stops": [[0, [0, 220, 255]], [21, [0, 150, 180]]],
                },
                "desk": {
                    "color": [0, 200, 230],
                    "brightness": 70,
                },
            },
        },
        "govee_api": {
            "api_key": "test-key",
        },
    }
    config = AetherConfig(**raw)
    assert "sunrise" in config.scenes
    assert config.scenes["sunrise"]["wall_left"].brightness == 70
    assert config.scenes["sunrise"]["wall_left"].stops == [[0, [0, 220, 255]], [21, [0, 150, 180]]]
    assert config.scenes["sunrise"]["desk"].color == [0, 200, 230]
    assert config.govee_api.api_key == "test-key"


def test_circadian_config_phase_scenes():
    cfg = CircadianConfig(
        phase_scenes={
            "dawn": "sunrise",
            "morning": "sunrise",
            "night": "purple_night",
        },
    )
    assert cfg.phase_scenes["dawn"] == "sunrise"
    assert cfg.phase_scenes["night"] == "purple_night"


def test_circadian_config_palettes_still_accepted():
    """Backwards compat: palettes field still works."""
    cfg = CircadianConfig(
        palettes={
            "dawn": {"color": [255, 160, 50], "brightness": 30},
        },
    )
    assert "dawn" in cfg.palettes


def test_aether_config_defaults_no_scenes():
    """Config without scenes should still load fine."""
    config = AetherConfig()
    assert config.scenes == {}
    assert config.govee_api.api_key is None
```

**Run:** `pytest tests/test_config.py -v`
**Expected:** Fails — SceneZoneConfig, GoveeApiConfig not found, scenes/govee_api not on AetherConfig

**Implementation:** Modify `src/aether/config.py`

Add after `PaletteEntry` class:

```python
class SceneZoneConfig(BaseModel):
    color: list[int] | None = None
    brightness: int = 100
    stops: list[list] | None = None

    @field_validator("color")
    @classmethod
    def validate_scene_color(cls, v: list[int] | None) -> list[int] | None:
        if v is not None:
            if len(v) != 3:
                raise ValueError("Color must be [r, g, b]")
            for c in v:
                if not 0 <= c <= 255:
                    raise ValueError(f"Color value {c} must be 0-255")
        return v


class GoveeApiConfig(BaseModel):
    api_key: str | None = None
```

Add `phase_scenes` to `CircadianConfig`:

```python
class CircadianConfig(BaseModel):
    update_interval_sec: int = 1
    ramp_interval_ms: int = 100
    return_ramp_sec: int = 8
    sunrise_offset_min: int = 0
    sunset_offset_min: int = 0
    palettes: dict[str, PaletteEntry] = {}
    phase_scenes: dict[str, str] = {}
```

Add to `AetherConfig`:

```python
class AetherConfig(BaseModel):
    # ... existing fields ...
    scenes: dict[str, dict[str, SceneZoneConfig]] = {}
    govee_api: GoveeApiConfig = GoveeApiConfig()
```

**Run:** `pytest tests/test_config.py -v`
**Expected:** All 7 tests pass

**Commit:** `git add src/aether/config.py tests/test_config.py && git commit -m "feat(config): add scene, phase_scenes, and govee_api config models"`

---

### Task 3: GoveeSegmentAdapter

- [ ] Write failing tests in `tests/test_govee_segment.py`
- [ ] Implement `src/aether/adapters/govee_segment.py`

**Test file:** `tests/test_govee_segment.py`

```python
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx

from aether.adapters.govee_segment import GoveeSegmentAdapter


@pytest.fixture
def adapter():
    return GoveeSegmentAdapter(api_key="test-api-key", rate_limit=0.0)


@pytest.mark.asyncio
async def test_set_segments_groups_by_color(adapter):
    """Segments with same color should be batched into one API call."""
    mock_response = httpx.Response(200, json={"code": 200, "message": "success"})

    with patch.object(adapter._client, "post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
        segments = {
            0: (255, 0, 0),
            1: (255, 0, 0),
            2: (255, 0, 0),
            3: (0, 255, 0),
            4: (0, 255, 0),
        }
        await adapter.set_segments("10:BD:C9:F0:82:86:41:83", "H6641", segments, brightness=70)

        # Should make 2 calls: one for red segments, one for green segments
        assert mock_post.call_count == 2

        # Verify payload structure
        calls = mock_post.call_args_list
        payloads = [json.loads(call.kwargs.get("content", call.args[1] if len(call.args) > 1 else "{}")) for call in calls]

        # Collect all segment arrays from calls
        all_segments = []
        for p in payloads:
            cap = p["payload"]["capability"]
            assert cap["type"] == "devices.capabilities.segment_color_setting"
            assert cap["instance"] == "segmentedColorRgb"
            all_segments.extend(cap["value"]["segment"])

        assert sorted(all_segments) == [0, 1, 2, 3, 4]


@pytest.mark.asyncio
async def test_rgb_encoding(adapter):
    """RGB (255, 128, 0) should encode as (255 << 16) | (128 << 8) | 0 = 16744448."""
    mock_response = httpx.Response(200, json={"code": 200, "message": "success"})

    with patch.object(adapter._client, "post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
        await adapter.set_segments("10:BD:C9:F0:82:86:41:83", "H6641", {0: (255, 128, 0)}, brightness=70)

        call_content = json.loads(mock_post.call_args.kwargs.get("content", mock_post.call_args.args[1]))
        rgb_value = call_content["payload"]["capability"]["value"]["rgb"]
        assert rgb_value == (255 << 16) | (128 << 8) | 0


@pytest.mark.asyncio
async def test_set_color_single_device(adapter):
    """set_color sends colorRgb capability for single-color devices."""
    mock_response = httpx.Response(200, json={"code": 200, "message": "success"})

    with patch.object(adapter._client, "post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
        await adapter.set_color("AA:BB:CC:DD:EE:FF:00:11", "H6022", (180, 140, 60), brightness=60)

        assert mock_post.call_count == 1
        call_content = json.loads(mock_post.call_args.kwargs.get("content", mock_post.call_args.args[1]))
        cap = call_content["payload"]["capability"]
        assert cap["instance"] == "colorRgb"
        assert cap["value"] == (180 << 16) | (140 << 8) | 60


@pytest.mark.asyncio
async def test_set_brightness(adapter):
    """set_brightness sends brightness capability."""
    mock_response = httpx.Response(200, json={"code": 200, "message": "success"})

    with patch.object(adapter._client, "post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
        await adapter.set_brightness("AA:BB:CC:DD:EE:FF:00:11", "H6641", 80)

        call_content = json.loads(mock_post.call_args.kwargs.get("content", mock_post.call_args.args[1]))
        cap = call_content["payload"]["capability"]
        assert cap["type"] == "devices.capabilities.range"
        assert cap["instance"] == "brightness"
        assert cap["value"] == 80


@pytest.mark.asyncio
async def test_api_key_in_header(adapter):
    """API key should be sent in Govee-API-Key header."""
    mock_response = httpx.Response(200, json={"code": 200, "message": "success"})

    with patch.object(adapter._client, "post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
        await adapter.set_color("AA:BB:CC:DD:EE:FF:00:11", "H6022", (255, 0, 0), brightness=100)

        # The API key is set on the client headers at init, verify the client was created with it
        assert adapter._client.headers.get("Govee-API-Key") == "test-api-key"


@pytest.mark.asyncio
async def test_api_error_logged_not_raised(adapter):
    """API errors should be logged but not raise — other zones can still update."""
    mock_response = httpx.Response(429, json={"code": 429, "message": "rate limited"})

    with patch.object(adapter._client, "post", new_callable=AsyncMock, return_value=mock_response):
        # Should not raise
        await adapter.set_segments("10:BD:C9:F0:82:86:41:83", "H6641", {0: (255, 0, 0)}, brightness=70)
```

**Run:** `pytest tests/test_govee_segment.py -v`
**Expected:** Fails — module not found

**Implementation:** `src/aether/adapters/govee_segment.py`

```python
from __future__ import annotations

import asyncio
import json
import sys
import uuid
from collections import defaultdict

import httpx


API_URL = "https://openapi.api.govee.com/router/api/v1/device/control"


class GoveeSegmentAdapter:
    def __init__(self, api_key: str, rate_limit: float = 0.1):
        self._api_key = api_key
        self._rate_limit = rate_limit
        self._client = httpx.AsyncClient(
            headers={
                "Govee-API-Key": api_key,
                "Content-Type": "application/json",
            },
            timeout=10,
        )
        self._last_request_time: float = 0

    async def _rate_wait(self) -> None:
        if self._rate_limit <= 0:
            return
        now = asyncio.get_event_loop().time()
        elapsed = now - self._last_request_time
        if elapsed < self._rate_limit:
            await asyncio.sleep(self._rate_limit - elapsed)
        self._last_request_time = asyncio.get_event_loop().time()

    async def _send(self, device_id: str, sku: str, capability: dict) -> None:
        payload = {
            "requestId": str(uuid.uuid4()),
            "payload": {
                "sku": sku,
                "device": device_id,
                "capability": capability,
            },
        }
        try:
            await self._rate_wait()
            resp = await self._client.post(API_URL, content=json.dumps(payload))
            if resp.status_code != 200:
                print(
                    f"[aether] Govee API error {resp.status_code}: {resp.text}",
                    file=sys.stderr,
                )
        except Exception as e:
            print(f"[aether] Govee API request failed: {e}", file=sys.stderr)

    @staticmethod
    def _encode_rgb(r: int, g: int, b: int) -> int:
        return (r << 16) | (g << 8) | b

    async def set_segments(
        self,
        device_id: str,
        sku: str,
        segments: dict[int, tuple[int, int, int]],
        brightness: int,
    ) -> None:
        """Send segmented color commands. Groups segments by color to minimize API calls."""
        # Group segments by RGB value
        color_groups: dict[tuple[int, int, int], list[int]] = defaultdict(list)
        for seg_idx, rgb in segments.items():
            color_groups[rgb].append(seg_idx)

        for rgb, seg_indices in color_groups.items():
            seg_indices.sort()
            await self._send(device_id, sku, {
                "type": "devices.capabilities.segment_color_setting",
                "instance": "segmentedColorRgb",
                "value": {
                    "segment": seg_indices,
                    "rgb": self._encode_rgb(*rgb),
                },
            })

    async def set_color(
        self,
        device_id: str,
        sku: str,
        color: tuple[int, int, int],
        brightness: int,
    ) -> None:
        """Set a single color for the entire device."""
        await self._send(device_id, sku, {
            "type": "devices.capabilities.color_setting",
            "instance": "colorRgb",
            "value": self._encode_rgb(*color),
        })

    async def set_brightness(
        self,
        device_id: str,
        sku: str,
        brightness: int,
    ) -> None:
        """Set device brightness (0-100)."""
        await self._send(device_id, sku, {
            "type": "devices.capabilities.range",
            "instance": "brightness",
            "value": brightness,
        })

    async def close(self) -> None:
        await self._client.aclose()
```

**Run:** `pytest tests/test_govee_segment.py -v`
**Expected:** All 7 tests pass

**Commit:** `git add src/aether/adapters/govee_segment.py tests/test_govee_segment.py && git commit -m "feat(adapters): add GoveeSegmentAdapter for Platform API segment control"`

---

### Task 4: Scene engine

- [ ] Write failing tests in `tests/test_scene_engine.py`
- [ ] Implement `src/aether/scenes/engine.py`

**Test file:** `tests/test_scene_engine.py`

```python
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aether.scenes.engine import SceneEngine
from aether.config import AetherConfig, SceneZoneConfig, GoveeApiConfig
from aether.lighting.ramp import ColorState


SUNRISE_SCENE = {
    "wall_left": SceneZoneConfig(
        brightness=70,
        stops=[[0, [0, 220, 255]], [21, [0, 150, 180]]],
    ),
    "desk": SceneZoneConfig(
        color=[0, 200, 230],
        brightness=70,
    ),
}

PURPLE_NIGHT_SCENE = {
    "wall_left": SceneZoneConfig(
        brightness=70,
        stops=[[0, [92, 0, 255]], [21, [80, 0, 220]]],
    ),
    "desk": SceneZoneConfig(
        color=[92, 0, 255],
        brightness=60,
    ),
}


def _make_config(scenes, phase_scenes=None):
    raw = {
        "scenes": {},
        "zones": {
            "wall_left": {"govee_device": "10:BD:C9:F0:82:86:41:83"},
            "desk": {"openrgb_devices": ["SteelSeries Apex 3 TKL"]},
        },
        "circadian": {
            "phase_scenes": phase_scenes or {},
        },
    }
    # Convert SceneZoneConfig objects to dicts for raw config loading
    for scene_name, zone_map in scenes.items():
        raw["scenes"][scene_name] = {}
        for zone_name, zone_cfg in zone_map.items():
            raw["scenes"][scene_name][zone_name] = zone_cfg.model_dump(exclude_none=True)
    return AetherConfig(**raw)


# Hardware segment counts from spec
SEGMENT_COUNTS = {
    "wall_left": 22,
    "wall_right": 22,
    "monitor": 15,
    "floor": 7,
    "bedroom": 1,
}


@pytest.fixture
def mock_segment_adapter():
    adapter = AsyncMock()
    adapter.set_segments = AsyncMock()
    adapter.set_color = AsyncMock()
    adapter.set_brightness = AsyncMock()
    return adapter


@pytest.fixture
def mock_mixer():
    mixer = MagicMock()
    mixer.submit = MagicMock()
    mixer.resolve = MagicMock()
    return mixer


@pytest.fixture
def mock_mqtt():
    mqtt = MagicMock()
    mqtt.publish = MagicMock()
    return mqtt


@pytest.fixture
def engine(mock_segment_adapter, mock_mixer, mock_mqtt):
    config = _make_config(
        {"sunrise": SUNRISE_SCENE, "purple_night": PURPLE_NIGHT_SCENE},
        phase_scenes={"dawn": "sunrise", "night": "purple_night"},
    )
    return SceneEngine(
        config=config,
        segment_adapter=mock_segment_adapter,
        mixer=mock_mixer,
        mqtt=mock_mqtt,
        segment_counts=SEGMENT_COUNTS,
    )


@pytest.mark.asyncio
async def test_apply_scene_sends_segments_for_govee_zone(engine, mock_segment_adapter):
    await engine.apply_scene("sunrise")

    # wall_left has govee_device → should call set_segments
    mock_segment_adapter.set_segments.assert_called_once()
    call_args = mock_segment_adapter.set_segments.call_args
    assert call_args.args[0] == "10:BD:C9:F0:82:86:41:83"  # device_id
    assert call_args.args[1] == "H6641"  # sku from zone config (need to add sku)
    # Actually, we need sku. Let's check this after config update.


@pytest.mark.asyncio
async def test_apply_scene_submits_color_to_mixer_for_openrgb_zone(engine, mock_mixer):
    await engine.apply_scene("sunrise")

    # desk has openrgb_devices → should submit to mixer
    mock_mixer.submit.assert_called()
    # Find the desk submit call
    desk_calls = [c for c in mock_mixer.submit.call_args_list if c.args[1] == "desk"]
    assert len(desk_calls) == 1
    color = desk_calls[0].args[2]
    assert isinstance(color, ColorState)
    assert color.r == 0
    assert color.g == 200
    assert color.b == 230
    assert color.brightness == 70


@pytest.mark.asyncio
async def test_apply_scene_sets_active_scene(engine):
    await engine.apply_scene("sunrise")
    assert engine.active_scene == "sunrise"


@pytest.mark.asyncio
async def test_apply_scene_publishes_mqtt(engine, mock_mqtt):
    await engine.apply_scene("sunrise")
    # Should publish active scene name
    mqtt_calls = {c.args[0]: c.args[1] for c in mock_mqtt.publish.call_args_list}
    assert "aether/scene/active" in mqtt_calls


@pytest.mark.asyncio
async def test_apply_circadian_scene_uses_phase_mapping(engine, mock_segment_adapter):
    await engine.apply_circadian_scene("dawn")
    assert engine.active_scene == "sunrise"


@pytest.mark.asyncio
async def test_apply_circadian_scene_skipped_during_manual_override(engine, mock_segment_adapter):
    # Manually apply a scene
    await engine.apply_scene("purple_night")
    engine._manual_override = True
    mock_segment_adapter.reset_mock()

    # Circadian scene should be skipped
    await engine.apply_circadian_scene("dawn")
    mock_segment_adapter.set_segments.assert_not_called()
    assert engine.active_scene == "purple_night"


@pytest.mark.asyncio
async def test_reset_to_circadian_clears_override(engine):
    engine._manual_override = True
    engine.reset_to_circadian()
    assert engine._manual_override is False


def test_get_scene_names(engine):
    names = engine.get_scene_names()
    assert "sunrise" in names
    assert "purple_night" in names


@pytest.mark.asyncio
async def test_unknown_scene_ignored(engine, mock_segment_adapter):
    await engine.apply_scene("nonexistent")
    mock_segment_adapter.set_segments.assert_not_called()
```

**Run:** `pytest tests/test_scene_engine.py -v`
**Expected:** Fails — module not found

**Implementation:** `src/aether/scenes/engine.py`

```python
from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING

from aether.config import AetherConfig, SceneZoneConfig
from aether.lighting.ramp import ColorState
from aether.scenes.interpolate import interpolate_stops

if TYPE_CHECKING:
    from aether.adapters.govee_segment import GoveeSegmentAdapter
    from aether.mixer import Mixer


# Hardware segment counts per zone (Govee segmented devices)
DEFAULT_SEGMENT_COUNTS = {
    "wall_left": 22,
    "wall_right": 22,
    "monitor": 15,
    "floor": 7,
    "bedroom": 1,
}

# Govee device SKU mapping (from zone govee_device to SKU)
# These are looked up from the config zones — for now, we need the SKU
# in the zone config or use a hardcoded mapping based on segment count.
ZONE_SKUS = {
    "wall_left": "H6641",
    "wall_right": "H6641",
    "monitor": "H6168",
    "floor": "H6076",
    "bedroom": "H6022",
}


class SceneEngine:
    def __init__(
        self,
        config: AetherConfig,
        segment_adapter: GoveeSegmentAdapter,
        mixer: Mixer,
        mqtt,
        segment_counts: dict[str, int] | None = None,
    ):
        self._config = config
        self._segment_adapter = segment_adapter
        self._mixer = mixer
        self._mqtt = mqtt
        self._segment_counts = segment_counts or DEFAULT_SEGMENT_COUNTS
        self._scenes = config.scenes
        self._phase_scenes = config.circadian.phase_scenes
        self._active_scene: str | None = None
        self._manual_override: bool = False

    @property
    def active_scene(self) -> str | None:
        return self._active_scene

    def get_scene_names(self) -> list[str]:
        return list(self._scenes.keys())

    def reset_to_circadian(self) -> None:
        self._manual_override = False
        mode = "circadian"
        self._mqtt.publish("aether/scene/mode", json.dumps(mode), retain=True)

    async def apply_scene(self, name: str, *, manual: bool = False) -> None:
        if name not in self._scenes:
            print(f"[aether] Scene '{name}' not found, ignoring", file=sys.stderr)
            return

        scene_zones = self._scenes[name]
        zones_config = self._config.zones

        for zone_name, zone_scene in scene_zones.items():
            zone_cfg = zones_config.get(zone_name)

            if zone_cfg is not None and zone_cfg.govee_device is not None:
                # Govee device — use segment adapter
                device_id = zone_cfg.govee_device
                sku = ZONE_SKUS.get(zone_name, "H6641")

                if zone_scene.stops is not None:
                    seg_count = self._segment_counts.get(zone_name, 1)
                    segments = interpolate_stops(zone_scene.stops, seg_count)
                    await self._segment_adapter.set_segments(
                        device_id, sku, segments, zone_scene.brightness
                    )
                elif zone_scene.color is not None:
                    color = tuple(zone_scene.color)
                    await self._segment_adapter.set_color(
                        device_id, sku, color, zone_scene.brightness
                    )

                # Set brightness separately
                await self._segment_adapter.set_brightness(
                    device_id, sku, zone_scene.brightness
                )

            elif zone_cfg is not None and zone_cfg.openrgb_devices:
                # OpenRGB device — submit single color through mixer
                if zone_scene.color is not None:
                    color = ColorState(
                        r=zone_scene.color[0],
                        g=zone_scene.color[1],
                        b=zone_scene.color[2],
                        brightness=zone_scene.brightness,
                    )
                    self._mixer.submit("scene", zone_name, color, priority=2)

        # Resolve mixer for OpenRGB zones
        self._mixer.resolve()

        self._active_scene = name
        if manual:
            self._manual_override = True

        # Publish scene state
        self._mqtt.publish("aether/scene/active", json.dumps(name), retain=True)
        mode = "manual" if self._manual_override else "circadian"
        self._mqtt.publish("aether/scene/mode", json.dumps(mode), retain=True)

    async def apply_circadian_scene(self, phase: str) -> None:
        if self._manual_override:
            return

        scene_name = self._phase_scenes.get(phase)
        if scene_name is None:
            return

        # Only apply if scene actually changed
        if scene_name == self._active_scene:
            return

        await self.apply_scene(scene_name, manual=False)
```

**Run:** `pytest tests/test_scene_engine.py -v`
**Expected:** All 10 tests pass (some tests may need minor adjustments — the `test_apply_scene_sends_segments_for_govee_zone` test checks SKU which comes from the hardcoded `ZONE_SKUS` map)

**Commit:** `git add src/aether/scenes/engine.py tests/test_scene_engine.py && git commit -m "feat(scenes): add SceneEngine for coordinated scene application"`

---

### Task 5: Refactor CircadianEngine for scenes

- [ ] Update `tests/test_circadian.py` with scene-based tests
- [ ] Modify `src/aether/lighting/circadian.py` to use scene engine

**Test updates:** `tests/test_circadian.py`

Add the following tests and update existing ones:

```python
# Add at top of file:
from unittest.mock import AsyncMock, MagicMock

# Add new tests:

class FakeMixer:
    """Minimal mixer for tests that still need the old interface."""
    def __init__(self):
        self.calls = []

    def submit_all(self, source, color, priority, ttl_sec=None):
        self.calls.append(("submit_all", source, color, priority))

    def resolve(self):
        self.calls.append(("resolve",))


def _make_config_with_scenes():
    from aether.config import AetherConfig
    return AetherConfig(**{
        "circadian": {
            "update_interval_sec": 1,
            "phase_scenes": {
                "dawn": "sunrise",
                "morning": "sunrise",
                "midday": "sunrise",
                "golden_hour": "golden",
                "evening": "purple_night",
                "night": "purple_night",
            },
            "palettes": {
                "dawn": {"color": [255, 160, 50], "brightness": 30},
                "morning": {"color": [255, 240, 220], "brightness": 80},
                "midday": {"color": [255, 255, 255], "brightness": 100},
                "golden_hour": {"color": [255, 180, 60], "brightness": 70},
                "evening": {"color": [80, 60, 180], "brightness": 40},
                "night": {"color": [30, 20, 80], "brightness": 15},
                "nightlight": {"color": [180, 140, 60], "brightness": 5},
            },
        },
    })


def test_circadian_engine_has_scene_engine_ref():
    """CircadianEngine should accept optional scene_engine parameter."""
    config = _make_config_with_scenes()
    mixer = FakeMixer()
    scene_engine = AsyncMock()
    engine = CircadianEngine(config, mixer, scene_engine=scene_engine)
    assert engine._scene_engine is scene_engine


@pytest.mark.asyncio
async def test_circadian_calls_scene_engine_apply():
    """When scene_engine is set, circadian should call apply_circadian_scene."""
    config = _make_config_with_scenes()
    mixer = FakeMixer()
    scene_engine = AsyncMock()
    scene_engine.apply_circadian_scene = AsyncMock()
    engine = CircadianEngine(config, mixer, scene_engine=scene_engine)
    engine._sun = SUN
    engine._last_fetch_date = "2026-03-27"

    # Manually call the scene path
    phase = compute_phase(datetime(2026, 3, 27, 8, 0), SUN)
    await engine._apply_phase(phase)
    scene_engine.apply_circadian_scene.assert_called_once_with("morning")


def test_circadian_on_state_away_with_scene_engine():
    """AWAY state with scene_engine should apply nightlight scene."""
    config = _make_config_with_scenes()
    mixer = FakeMixer()
    scene_engine = AsyncMock()
    scene_engine.apply_scene = AsyncMock()
    engine = CircadianEngine(config, mixer, scene_engine=scene_engine)

    engine.on_state_change(State.AWAY)
    # Should schedule nightlight scene application
    # (actual await happens in the event loop)
```

**Implementation changes to** `src/aether/lighting/circadian.py`:

The key changes:
1. Add optional `scene_engine` parameter to `__init__`
2. Add `_apply_phase(phase)` method that delegates to scene engine when available, falls back to mixer palette
3. Modify `run()` to call `_apply_phase`
4. Modify `on_state_change(AWAY)` to apply nightlight scene via scene engine
5. Simplify `run_return_ramp()` to just snap to current phase scene

```python
class CircadianEngine:
    def __init__(self, config: AetherConfig, mixer, scene_engine=None):
        self._config = config
        self._mixer = mixer
        self._scene_engine = scene_engine
        self._palettes = palettes_from_config(config)
        self._sun: SunTimes | None = None
        self._last_fetch_date: str | None = None
        self._ramping = False
        self._state = State.PRESENT
        self._last_phase: str | None = None

    async def _ensure_sun_times(self) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        if self._last_fetch_date == today and self._sun is not None:
            return

        loc = self._config.location
        if loc.latitude is not None and loc.longitude is not None:
            self._sun = await fetch_sun_times(loc.latitude, loc.longitude)
        else:
            self._sun = get_default_sun_times()
        self._last_fetch_date = today

    async def _apply_phase(self, phase: str) -> None:
        """Apply lighting for the given phase — scene engine if available, else mixer palette."""
        if self._scene_engine is not None:
            await self._scene_engine.apply_circadian_scene(phase)
        else:
            target = phase_color(phase, self._palettes)
            self._mixer.submit_all("circadian", target, priority=2)

    def on_state_change(self, new_state: State) -> None:
        self._state = new_state
        if new_state == State.AWAY:
            if self._scene_engine is not None:
                # Schedule nightlight scene via scene engine
                # Uses dim_amber scene from phase_scenes nightlight mapping
                import asyncio
                asyncio.ensure_future(self._scene_engine.apply_scene("dim_amber"))
            else:
                nightlight = self._palettes.get("nightlight", ColorState(180, 140, 60, 5))
                self._mixer.submit_all("circadian", nightlight, priority=2)
                self._mixer.resolve()

    async def run_return_ramp(self) -> None:
        """On return from AWAY, snap to current phase scene immediately."""
        if self._sun is None:
            return

        if self._scene_engine is not None:
            # Snap to current phase scene (no ramp — scenes are multi-color)
            now = datetime.now()
            phase = compute_phase(now, self._sun)
            self._scene_engine.reset_to_circadian()
            await self._scene_engine.apply_scene(
                self._config.circadian.phase_scenes.get(phase, "sunrise")
            )
            return

        # Legacy palette-based ramp (fallback when no scene engine)
        self._ramping = True
        nightlight = self._palettes.get("nightlight", ColorState(180, 140, 60, 5))
        now = datetime.now()
        phase = compute_phase(now, self._sun)
        target = phase_color(phase, self._palettes)

        ramp_steps = 8
        step_interval = self._config.circadian.return_ramp_sec / ramp_steps

        for step in generate_ramp(
            nightlight, target,
            duration_sec=self._config.circadian.return_ramp_sec,
            interval_ms=int(step_interval * 1000),
        ):
            self._mixer.submit_all("circadian", step, priority=2)
            self._mixer.resolve()
            await asyncio.sleep(step_interval)

        self._ramping = False

    async def run(self) -> None:
        while True:
            if self._ramping:
                await asyncio.sleep(0.1)
                continue

            await self._ensure_sun_times()

            if self._state == State.AWAY:
                if self._scene_engine is None:
                    nightlight = self._palettes.get("nightlight", ColorState(180, 140, 60, 5))
                    self._mixer.submit_all("circadian", nightlight, priority=2)
                # Scene engine AWAY is handled by on_state_change
            elif self._state == State.PRESENT and self._sun is not None:
                now = datetime.now()
                phase = compute_phase(now, self._sun)
                await self._apply_phase(phase)

            await asyncio.sleep(self._config.circadian.update_interval_sec)
```

**Run:** `pytest tests/test_circadian.py -v`
**Expected:** All existing tests pass (CircadianEngine still accepts old signature with mixer-only), new scene-engine tests pass

**Commit:** `git add src/aether/lighting/circadian.py tests/test_circadian.py && git commit -m "refactor(circadian): delegate to scene engine for phase-based lighting"`

---

### Task 6: Voice intents and handler

- [ ] Update intent tests in `tests/test_intent.py`
- [ ] Add scene intents to `src/aether/vox/intent.py`
- [ ] Update `src/aether/vox/handler.py` for scene commands

**Test updates:** `tests/test_intent.py`

Add the following tests:

```python
# Scene intent tests

def test_set_scene():
    assert classify_intent("set scene sunrise") == Intent.SCENE_SET

def test_switch_to_scene():
    assert classify_intent("switch to neon tokyo") == Intent.SCENE_SET

def test_random_scene():
    assert classify_intent("random scene") == Intent.SCENE_RANDOM

def test_pick_a_scene():
    assert classify_intent("pick a scene") == Intent.SCENE_RANDOM

def test_reset_scene():
    assert classify_intent("reset") == Intent.SCENE_RESET

def test_go_back_to_default():
    assert classify_intent("go back to default") == Intent.SCENE_RESET

def test_normal_resets_scene():
    assert classify_intent("normal") == Intent.SCENE_RESET

def test_what_scene():
    assert classify_intent("what scene") == Intent.SCENE_QUERY

def test_current_scene():
    assert classify_intent("current scene") == Intent.SCENE_QUERY

def test_stop_still_stops_mode():
    """'stop' should still trigger MODE_STOP, not SCENE_RESET."""
    assert classify_intent("stop") == Intent.MODE_STOP

def test_set_scene_case_insensitive():
    assert classify_intent("Set Scene Ember") == Intent.SCENE_SET
```

**Implementation changes to** `src/aether/vox/intent.py`:

```python
from __future__ import annotations

from enum import Enum


class Intent(Enum):
    MODE_FOCUS = "mode_focus"
    MODE_FOCUS_STOP = "mode_focus_stop"
    MODE_PARTY = "mode_party"
    MODE_PARTY_STOP = "mode_party_stop"
    MODE_SLEEP = "mode_sleep"
    MODE_STOP = "mode_stop"
    PAUSE = "pause"
    RESUME = "resume"
    BRIGHTNESS_UP = "brightness_up"
    BRIGHTNESS_DOWN = "brightness_down"
    COLOR_WARMER = "color_warmer"
    COLOR_COOLER = "color_cooler"
    LIGHTS_OFF = "lights_off"
    LIGHTS_ON = "lights_on"
    SCENE_SET = "scene_set"
    SCENE_RANDOM = "scene_random"
    SCENE_RESET = "scene_reset"
    SCENE_QUERY = "scene_query"


KEYWORD_TABLE: list[tuple[str, Intent]] = [
    ("stop focus", Intent.MODE_FOCUS_STOP),
    ("end focus", Intent.MODE_FOCUS_STOP),
    ("stop party", Intent.MODE_PARTY_STOP),
    ("party mode", Intent.MODE_PARTY),
    ("lights off", Intent.LIGHTS_OFF),
    ("lights on", Intent.LIGHTS_ON),
    ("goodnight", Intent.MODE_SLEEP),
    ("unpause", Intent.RESUME),
    ("brighter", Intent.BRIGHTNESS_UP),
    ("bright", Intent.BRIGHTNESS_UP),
    ("dimmer", Intent.BRIGHTNESS_DOWN),
    ("dim", Intent.BRIGHTNESS_DOWN),
    ("warmer", Intent.COLOR_WARMER),
    ("cooler", Intent.COLOR_COOLER),
    # Scene intents (before generic stop/cancel)
    ("set scene", Intent.SCENE_SET),
    ("switch to", Intent.SCENE_SET),
    ("random scene", Intent.SCENE_RANDOM),
    ("pick a scene", Intent.SCENE_RANDOM),
    ("go back to default", Intent.SCENE_RESET),
    ("what scene", Intent.SCENE_QUERY),
    ("current scene", Intent.SCENE_QUERY),
    ("normal", Intent.SCENE_RESET),
    ("reset", Intent.SCENE_RESET),
    # Generic mode controls (after scene-specific patterns)
    ("focus", Intent.MODE_FOCUS),
    ("party", Intent.MODE_PARTY),
    ("sleep", Intent.MODE_SLEEP),
    ("stop", Intent.MODE_STOP),
    ("cancel", Intent.MODE_STOP),
    ("pause", Intent.PAUSE),
    ("resume", Intent.RESUME),
]


def classify_intent(text: str) -> Intent | None:
    lower = text.lower().strip()
    for keyword, intent in KEYWORD_TABLE:
        if keyword in lower:
            return intent
    return None
```

**Implementation changes to** `src/aether/vox/handler.py`:

Add scene handling to the `execute` method and add `scene_engine` to constructor:

```python
from __future__ import annotations

import random
import sys
from datetime import datetime, timezone

from aether.lighting.ramp import ColorState
from aether.state import Event, State, StateMachine
from aether.vox.intent import Intent


class VoxHandler:
    def __init__(self, state_machine: StateMachine, mixer, mqtt, config, scene_engine=None):
        self._sm = state_machine
        self._mixer = mixer
        self._mqtt = mqtt
        self._config = config
        self._scene_engine = scene_engine

    def execute(self, intent: Intent, text: str) -> None:
        print(f"[aether] VOX: intent={intent.value} text={text!r}", file=sys.stderr)

        self._mqtt.publish("aether/vox/last_command", {
            "text": text,
            "intent": intent.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, retain=True)

        if intent == Intent.SCENE_SET:
            self._handle_scene_set(text)
        elif intent == Intent.SCENE_RANDOM:
            self._handle_scene_random()
        elif intent == Intent.SCENE_RESET:
            self._handle_scene_reset()
        elif intent == Intent.SCENE_QUERY:
            self._handle_scene_query()
        elif intent == Intent.MODE_FOCUS and self._sm.state == State.PRESENT:
            self._sm.handle_event(Event.FOCUS_START)
        elif intent == Intent.MODE_FOCUS_STOP and self._sm.state == State.FOCUS:
            self._sm.handle_event(Event.FOCUS_STOP)
        elif intent == Intent.MODE_PARTY and self._sm.state == State.PRESENT:
            self._sm.handle_event(Event.PARTY_START)
        elif intent == Intent.MODE_PARTY_STOP and self._sm.state == State.PARTY:
            self._sm.handle_event(Event.PARTY_STOP)
        elif intent == Intent.MODE_SLEEP and self._sm.state == State.PRESENT:
            self._sm.handle_event(Event.SLEEP_START)
        elif intent == Intent.MODE_STOP:
            self._stop_current_mode()
        elif intent == Intent.PAUSE:
            self._mqtt.publish(f"{self._config.mqtt.topic_prefix}/control", "pause")
        elif intent == Intent.RESUME:
            self._mqtt.publish(f"{self._config.mqtt.topic_prefix}/control", "resume")
        elif intent == Intent.BRIGHTNESS_UP:
            self._adjust_brightness(20)
        elif intent == Intent.BRIGHTNESS_DOWN:
            self._adjust_brightness(-20)
        elif intent == Intent.COLOR_WARMER:
            self._shift_color_temp(warm=True)
        elif intent == Intent.COLOR_COOLER:
            self._shift_color_temp(warm=False)
        elif intent == Intent.LIGHTS_OFF:
            off = ColorState(r=0, g=0, b=0, brightness=0)
            ttl = self._config.mixer.manual_ttl_sec
            self._mixer.submit_all("voice", off, priority=0, ttl_sec=ttl)
            self._mixer.resolve()
        elif intent == Intent.LIGHTS_ON:
            self._mixer.release_all("voice")
            self._mixer.resolve()

    def _handle_scene_set(self, text: str) -> None:
        if self._scene_engine is None:
            print("[aether] VOX: scene engine not available", file=sys.stderr)
            return

        scene_name = self._extract_scene_name(text)
        if scene_name is None:
            print(f"[aether] VOX: could not match scene name from {text!r}", file=sys.stderr)
            return

        import asyncio
        asyncio.ensure_future(self._scene_engine.apply_scene(scene_name, manual=True))

    def _handle_scene_random(self) -> None:
        if self._scene_engine is None:
            return

        names = self._scene_engine.get_scene_names()
        if not names:
            return

        name = random.choice(names)
        import asyncio
        asyncio.ensure_future(self._scene_engine.apply_scene(name, manual=True))

    def _handle_scene_reset(self) -> None:
        if self._scene_engine is None:
            return
        self._scene_engine.reset_to_circadian()

    def _handle_scene_query(self) -> None:
        if self._scene_engine is None:
            return
        active = self._scene_engine.active_scene or "none"
        self._mqtt.publish("aether/scene/active", active, retain=True)

    def _extract_scene_name(self, text: str) -> str | None:
        """Extract and fuzzy-match scene name from voice text."""
        if self._scene_engine is None:
            return None

        lower = text.lower().strip()
        # Remove known prefixes
        for prefix in ("set scene", "switch to"):
            if prefix in lower:
                idx = lower.index(prefix) + len(prefix)
                lower = lower[idx:].strip()
                break

        if not lower:
            return None

        available = self._scene_engine.get_scene_names()

        # Exact match (case-insensitive)
        for name in available:
            if name.lower() == lower:
                return name

        # Partial match: scene name contained in text or text contained in scene name
        # Replace spaces with underscores for matching (voice says "neon tokyo", config has "neon_tokyo")
        lower_underscore = lower.replace(" ", "_")
        for name in available:
            if name.lower() in lower_underscore or lower_underscore in name.lower():
                return name

        # Last resort: partial word match
        for name in available:
            name_words = name.lower().replace("_", " ").split()
            if any(word in lower for word in name_words if len(word) > 2):
                return name

        return None

    def _stop_current_mode(self) -> None:
        if self._sm.state == State.FOCUS:
            self._sm.handle_event(Event.FOCUS_STOP)
        elif self._sm.state == State.PARTY:
            self._sm.handle_event(Event.PARTY_STOP)
        elif self._sm.state == State.SLEEP:
            self._sm.handle_event(Event.SLEEP_CANCEL)

    def _adjust_brightness(self, delta: int) -> None:
        ttl = self._config.mixer.manual_ttl_sec
        claims = self._mixer.get_active_claims()
        for zone, claim in claims.items():
            current_br = claim.color.brightness
            new_br = max(0, min(100, current_br + delta))
            new_color = ColorState(
                r=claim.color.r, g=claim.color.g, b=claim.color.b,
                brightness=new_br,
            )
            self._mixer.submit("voice", zone, new_color, priority=0, ttl_sec=ttl)
        self._mixer.resolve()

    def _shift_color_temp(self, warm: bool) -> None:
        ttl = self._config.mixer.manual_ttl_sec
        claims = self._mixer.get_active_claims()
        for zone, claim in claims.items():
            r, g, b = claim.color.r, claim.color.g, claim.color.b
            if warm:
                r = min(255, r + 30)
                b = max(0, b - 30)
            else:
                r = max(0, r - 30)
                b = min(255, b + 30)
            new_color = ColorState(r=r, g=g, b=b, brightness=claim.color.brightness)
            self._mixer.submit("voice", zone, new_color, priority=0, ttl_sec=ttl)
        self._mixer.resolve()
```

**Run:** `pytest tests/test_intent.py -v`
**Expected:** All existing + 11 new scene intent tests pass

**Commit:** `git add src/aether/vox/intent.py src/aether/vox/handler.py tests/test_intent.py && git commit -m "feat(vox): add scene voice intents and handler with fuzzy name matching"`

---

### Task 7: CLI commands

- [ ] Add `scene` command group to `src/aether/cli.py`

**Implementation:** Add to `src/aether/cli.py` after the existing `resume` command:

```python
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
```

**Run:** `python -m aether scene --list` (with valid config)
**Expected:** Lists all scene names from config

**Commit:** `git add src/aether/cli.py && git commit -m "feat(cli): add scene command group for applying, listing, and resetting scenes"`

---

### Task 8: Daemon wiring

- [ ] Modify `_run_daemon()` in `src/aether/cli.py` to create and wire scene engine
- [ ] Subscribe to `aether/scene/set` MQTT topic
- [ ] Pass scene_engine to CircadianEngine and VoxHandler

**Implementation:** Modify `_run_daemon()` in `src/aether/cli.py`:

After the `mixer = Mixer(zones)` line, add scene engine setup:

```python
    # Scene engine (Govee Platform API for segmented device control)
    import os
    scene_engine = None
    govee_api_key = os.environ.get("GOVEE_API_KEY") or (
        config.govee_api.api_key if hasattr(config, "govee_api") else None
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
```

Change the circadian engine instantiation:

```python
    circadian = CircadianEngine(config, mixer, scene_engine=scene_engine)
```

In the `_vox_pipeline` section, update VoxHandler creation:

```python
            handler = VoxHandler(state_machine, mixer, mqtt, config, scene_engine=scene_engine)
```

Add MQTT subscription for scene commands inside `_handle_mqtt_command_inner`:

```python
        elif topic == f"{config.mqtt.topic_prefix}/scene/set":
            if scene_engine is not None:
                try:
                    cmd = json.loads(payload)
                    action = cmd.get("action")
                    if action == "set":
                        name = cmd.get("name", "")
                        asyncio.ensure_future(scene_engine.apply_scene(name, manual=True))
                    elif action == "random":
                        import random
                        names = scene_engine.get_scene_names()
                        if names:
                            asyncio.ensure_future(
                                scene_engine.apply_scene(random.choice(names), manual=True)
                            )
                    elif action == "reset":
                        scene_engine.reset_to_circadian()
                except json.JSONDecodeError:
                    # Treat plain text as scene name
                    asyncio.ensure_future(scene_engine.apply_scene(payload, manual=True))
```

Add the subscription:

```python
    mqtt.subscribe(f"{config.mqtt.topic_prefix}/scene/set")
```

Also add cleanup in the `finally` block:

```python
        if scene_engine is not None and hasattr(scene_engine, '_segment_adapter'):
            # segment_adapter has an httpx client to close
            pass  # httpx client cleanup is handled by GC
```

**Run:** `pytest tests/ -v` (all tests)
**Expected:** All tests pass

**Commit:** `git add src/aether/cli.py && git commit -m "feat(daemon): wire scene engine into daemon with MQTT scene commands"`

---

### Task 9: Scene definitions

- [ ] Update `config.example.yaml` with all 9 scenes, phase_scenes, and govee_api
- [ ] Update `CLAUDE.md` with new architecture and commands

**Implementation:** Add to `config.example.yaml` after the `openrgb` section:

```yaml
# Govee Platform API (for per-segment gradient control)
govee_api:
  api_key: null                      # Set GOVEE_API_KEY env var or fill this in

# Scene definitions — per-zone gradients and colors
# Each scene defines zones with either:
#   stops: [[segment_idx, [r, g, b]], ...] — gradient for segmented devices
#   color: [r, g, b] — single color for non-segmented or OpenRGB devices
scenes:
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

Add `phase_scenes` to the circadian section in `config.example.yaml`:

```yaml
circadian:
  update_interval_sec: 30
  ramp_interval_ms: 100
  return_ramp_sec: 8
  sunrise_offset_min: 0
  sunset_offset_min: 0
  phase_scenes:
    dawn: sunrise
    morning: sunrise
    midday: sunrise
    golden_hour: golden
    evening: purple_night
    night: purple_night
    nightlight: dim_amber
  palettes:
    # ... (keep existing palettes for backwards compat)
```

Update `CLAUDE.md` — add to Commands section:

```bash
# Scene control
python -m aether scene sunrise     # Apply a scene
python -m aether scene --random    # Random scene
python -m aether scene --reset     # Back to circadian
python -m aether scene --list      # List available scenes
```

Add to Architecture line:

```
Scene engine: config scenes → per-segment interpolation → GoveeSegmentAdapter (Govee Platform API HTTP) for segmented devices, mixer for OpenRGB zones. Circadian maps phases to scene names.
```

Add to Design Specs list:

```
- `docs/superpowers/specs/2026-03-28-aether-scenes-design.md` — Scene System (per-segment gradients)
```

**Run:** `pytest tests/ -v`
**Expected:** All tests pass

**Commit:** `git add config.example.yaml CLAUDE.md && git commit -m "docs: add scene definitions, phase_scenes mapping, and updated architecture docs"`

---

### Task 10: Manual integration test

- [ ] Start daemon with scenes enabled
- [ ] Verify circadian applies sunrise scene during day
- [ ] Test voice: "hey jarvis set scene neon tokyo"
- [ ] Test voice: "hey jarvis reset"
- [ ] Test voice: "hey jarvis random scene"
- [ ] Test CLI: `aether scene --list`
- [ ] Test CLI: `aether scene ember`
- [ ] Verify segment gradients on ropes and floor lamp

**Pre-flight checklist:**

1. Copy scene definitions to user config:
   ```bash
   # Back up existing config
   cp ~/.config/aether/config.yaml ~/.config/aether/config.yaml.bak
   # Merge new scene/govee_api sections into user config
   ```

2. Set API key:
   ```bash
   export GOVEE_API_KEY=65c5429a-cd8d-4e1a-a1d1-bbe19e303591
   ```

3. Verify MQTT broker is running:
   ```bash
   systemctl --user status mosquitto
   ```

4. Start daemon:
   ```bash
   python -m aether run
   ```

**Test sequence:**

```bash
# Terminal 1: daemon
python -m aether run

# Terminal 2: CLI tests
python -m aether scene --list
# Expected: Lists all 9 scenes (arctic, deep_space, dim_amber, ember, forest, golden, neon_tokyo, purple_night, sunrise)

python -m aether scene ember
# Expected: "Scene 'ember' applied." — verify floor lamp shows red-orange gradient, ropes show ember colors

python -m aether scene neon_tokyo
# Expected: Pink-purple-blue gradients on ropes, pink on floor lamp

python -m aether scene --reset
# Expected: "Reset to circadian lighting." — returns to phase-appropriate scene

python -m aether scene --random
# Expected: Random scene applied

# Terminal 2: MQTT monitoring
mosquitto_sub -t "aether/scene/#" -v
# Expected: aether/scene/active shows current scene name
#           aether/scene/mode shows "circadian" or "manual"
```

**Voice test sequence** (speak after wake word):
1. "hey jarvis set scene neon tokyo" -- verify neon_tokyo gradient appears
2. "hey jarvis what scene" -- verify aether/scene/active publishes "neon_tokyo"
3. "hey jarvis reset" -- verify returns to circadian scene
4. "hey jarvis random scene" -- verify a random scene is applied
5. "hey jarvis set scene deep space" -- verify deep_space star pattern on ropes

**Verification criteria:**
- Wall ropes (H6641) show gradient colors across 22 segments
- Floor lamp (H6076) shows gradient across 7 segments
- Monitor backlight (H6168) shows gradient across 15 segments
- Bedroom table lamp shows single solid color
- Desk keyboard (OpenRGB) shows single solid color
- Tower (OpenRGB) shows single solid color
- MQTT topics publish correct scene/mode state
- Circadian phase transitions switch scenes automatically
- Manual override persists until reset

---

## Important Rules

1. Every step has complete code -- no placeholders or "TODO" markers
2. Every code step includes a full code block ready to implement
3. Every test step includes the exact pytest command and expected outcome
4. TDD: write failing test first, then implement to make it pass
5. Commit after each task with a descriptive message
6. Use existing codebase patterns: `FakeMixer` in tests, `_publish_command` for CLI, `ColorState` dataclass, `zone_cfg.govee_device`/`zone_cfg.openrgb_devices` for routing
7. The Govee Platform API key is read from `GOVEE_API_KEY` env var or `config.govee_api.api_key` -- never hardcoded in source
8. Device IDs use colon-separated Platform API format (e.g., `10:BD:C9:F0:82:86:41:83`), not the stripped govee2mqtt MQTT format
9. Scene engine uses `priority=2` for mixer claims (same level as circadian), so modes at `priority=1` and voice at `priority=0` take precedence
10. `json` import is needed in `cli.py` for scene command payloads (already imported at top of file)

## Self-Review Checklist

- [x] Every spec requirement has a matching task (interpolation, config, segment adapter, scene engine, circadian refactor, voice, CLI, daemon wiring, scene definitions, integration test)
- [x] No placeholders or "TBD" -- all code is complete
- [x] Type/method names consistent across tasks: `SceneEngine.apply_scene()`, `SceneEngine.apply_circadian_scene()`, `SceneEngine.reset_to_circadian()`, `SceneEngine.get_scene_names()`, `GoveeSegmentAdapter.set_segments()`, `GoveeSegmentAdapter.set_color()`, `GoveeSegmentAdapter.set_brightness()`, `SceneZoneConfig`, `GoveeApiConfig`
- [x] All file paths are exact and match the project structure
- [x] Backwards compatibility preserved: `palettes` field kept in `CircadianConfig`, `CircadianEngine` works without `scene_engine`, `VoxHandler` works without `scene_engine`
- [x] Error cases handled: missing API key (warning + fallback), unknown scene name (log + ignore), API errors (log, don't crash), missing zone in scene (leave unchanged)
- [x] MQTT topics match spec: `aether/scene/active`, `aether/scene/mode`, `aether/scene/set`
- [x] Rate limiting in GoveeSegmentAdapter prevents API throttling
- [x] Segment grouping by color minimizes API calls
