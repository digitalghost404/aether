import pytest
from pathlib import Path
from aether.config import AetherConfig, load_config


def test_load_example_config(tmp_path):
    """Example config should parse without errors."""
    example = Path(__file__).parent.parent / "config.example.yaml"
    config = load_config(example)
    assert config.presence.camera_index == 0
    assert config.presence.absence_timeout_sec == 10
    assert config.presence.frame_interval_ms == 333
    assert config.mqtt.broker == "localhost"
    assert config.mqtt.port == 1883
    assert config.circadian.return_ramp_sec == 8
    assert len(config.circadian.palettes) == 7
    assert "dawn" in config.circadian.palettes
    assert "nightlight" in config.circadian.palettes


def test_palette_color_validation():
    """Colors must be 3-element lists with values 0-255."""
    from aether.config import PaletteEntry
    entry = PaletteEntry(color=[255, 180, 60], brightness=80)
    assert entry.color == [255, 180, 60]
    assert entry.brightness == 80


def test_palette_brightness_clamped():
    """Brightness must be 0-100."""
    from aether.config import PaletteEntry
    with pytest.raises(Exception):
        PaletteEntry(color=[255, 180, 60], brightness=150)


def test_missing_config_copies_example(tmp_path):
    """Missing config should copy example and raise SystemExit."""
    missing = tmp_path / "nonexistent.yaml"
    with pytest.raises(SystemExit):
        load_config(missing)


def test_default_zones():
    """Config should define all 5 zones."""
    example = Path(__file__).parent.parent / "config.example.yaml"
    config = load_config(example)
    assert set(config.zones.keys()) == {"wall_left", "wall_right", "monitor", "floor", "bedroom"}
