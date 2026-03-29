from aether.config import AetherConfig, FocusConfig, PartyConfig, SleepConfig


def test_focus_config_defaults():
    cfg = FocusConfig()
    assert cfg.work_min == 25
    assert cfg.short_break_min == 5
    assert cfg.long_break_min == 15
    assert cfg.cycles == 4
    assert cfg.work_color == [255, 255, 255]
    assert cfg.work_brightness == 100
    assert cfg.rope_dim_brightness == 10
    assert cfg.break_color == [180, 230, 180]
    assert cfg.break_brightness == 10


def test_party_config_defaults():
    cfg = PartyConfig()
    assert cfg.accent_zone == "floor"
    assert cfg.accent_brightness_low == 40
    assert cfg.accent_brightness_high == 100
    assert cfg.base_shift_beats == 8
    assert cfg.silence_timeout_sec == 120
    assert len(cfg.palette) == 4


def test_sleep_config_defaults():
    cfg = SleepConfig()
    assert cfg.total_duration_min == 5
    assert cfg.bedroom_final_color == [200, 100, 30]
    assert cfg.bedroom_final_brightness == 5


def test_aether_config_includes_new_sections():
    cfg = AetherConfig()
    assert isinstance(cfg.focus, FocusConfig)
    assert isinstance(cfg.party, PartyConfig)
    assert isinstance(cfg.sleep, SleepConfig)
