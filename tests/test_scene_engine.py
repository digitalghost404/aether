import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

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
            "desk": {"openrgb_devices": ["SteelSeries Apex 7 TKL"]},
        },
        "circadian": {
            "phase_scenes": phase_scenes or {},
        },
    }
    for scene_name, zone_map in scenes.items():
        raw["scenes"][scene_name] = {}
        for zone_name, zone_cfg in zone_map.items():
            raw["scenes"][scene_name][zone_name] = zone_cfg.model_dump(exclude_none=True)
    return AetherConfig(**raw)


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
    mock_segment_adapter.set_segments.assert_called_once()
    call_args = mock_segment_adapter.set_segments.call_args
    assert call_args.args[0] == "10:BD:C9:F0:82:86:41:83"


@pytest.mark.asyncio
async def test_apply_scene_submits_color_to_mixer_for_openrgb_zone(engine, mock_mixer):
    await engine.apply_scene("sunrise")
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
    mqtt_calls = {c.args[0]: c.args[1] for c in mock_mqtt.publish.call_args_list}
    assert "aether/scene/active" in mqtt_calls


@pytest.mark.asyncio
async def test_apply_circadian_scene_uses_phase_mapping(engine):
    await engine.apply_circadian_scene("dawn")
    assert engine.active_scene == "sunrise"


@pytest.mark.asyncio
async def test_apply_circadian_scene_skipped_during_manual_override(engine, mock_segment_adapter):
    await engine.apply_scene("purple_night")
    engine._manual_override = True
    mock_segment_adapter.reset_mock()
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
