import pytest
from pathlib import Path
from aether.config import AetherConfig, load_config, OpenRGBConfig, ZoneConfig, FocusConfig


def test_load_example_config(tmp_path):
    """Example config should parse without errors."""
    example = Path(__file__).parent.parent / "config.example.yaml"
    config = load_config(example)
    assert config.presence.camera_index == 0
    assert config.presence.absence_timeout_sec == 10
    assert config.presence.frame_interval_ms == 100
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


def test_openrgb_config_defaults():
    cfg = OpenRGBConfig()
    assert cfg.enabled is False
    assert cfg.host == "localhost"
    assert cfg.port == 6820
    assert cfg.retry_attempts == 3
    assert cfg.retry_delay_sec == 2.0


def test_zone_config_openrgb_devices():
    cfg = ZoneConfig(openrgb_devices=["SteelSeries Apex 3 TKL", "SteelSeries Rival 600"])
    assert cfg.openrgb_devices == ["SteelSeries Apex 3 TKL", "SteelSeries Rival 600"]
    assert cfg.govee_device is None


def test_zone_config_govee_device_no_openrgb():
    cfg = ZoneConfig(govee_device="AABBCCDDEEFF")
    assert cfg.govee_device == "AABBCCDDEEFF"
    assert cfg.openrgb_devices is None


def test_focus_config_desk_tower_defaults():
    cfg = FocusConfig()
    assert cfg.desk_color == [255, 223, 191]
    assert cfg.desk_brightness == 80
    assert cfg.tower_brightness == 10


def test_party_config_peripheral_defaults():
    from aether.config import PartyConfig
    cfg = PartyConfig()
    assert cfg.tower_beat_sync is True
    assert cfg.desk_accent is True


def test_aether_config_has_openrgb():
    from aether.config import AetherConfig, OpenRGBConfig
    cfg = AetherConfig()
    assert isinstance(cfg.openrgb, OpenRGBConfig)
    assert cfg.openrgb.enabled is False
