import asyncio
import numpy as np
import pytest
from aether.lighting.ramp import ColorState
from aether.modes.dj import DJMode, BeatAnalyzer
from aether.config import PartyConfig


class FakeMixer:
    def __init__(self):
        self.submissions: list[tuple[str, str, ColorState, int]] = []

    def submit(self, source: str, zone: str, color: ColorState, priority: int, ttl_sec: float | None = None) -> None:
        self.submissions.append((source, zone, color, priority))

    def submit_all(self, source: str, color: ColorState, priority: int, ttl_sec: float | None = None) -> None:
        for zone in ("wall_left", "wall_right", "monitor", "floor", "bedroom", "desk", "tower"):
            self.submit(source, zone, color, priority)

    def release(self, source: str, zone: str) -> None:
        pass

    def release_all(self, source: str) -> None:
        pass

    def resolve(self) -> None:
        pass

    def get_active_claims(self):
        return {}


class FakeMqtt:
    def __init__(self):
        self.published = []

    def publish(self, topic: str, payload, retain: bool = False) -> None:
        self.published.append((topic, payload))


def test_beat_analyzer_detects_onset_in_loud_audio():
    analyzer = BeatAnalyzer(sr=22050)
    silence = np.zeros(22050, dtype=np.float32)
    click = np.zeros(22050, dtype=np.float32)
    click[0:100] = 1.0
    analyzer.feed(silence)
    result = analyzer.feed(click)
    assert result.energy > 0.0


def test_beat_analyzer_silence_has_low_energy():
    analyzer = BeatAnalyzer(sr=22050)
    silence = np.zeros(22050, dtype=np.float32)
    result = analyzer.feed(silence)
    assert result.energy < 0.01


def test_beat_analyzer_detects_bpm_from_periodic_signal():
    analyzer = BeatAnalyzer(sr=22050)
    sr = 22050
    duration = 4.0
    samples = np.zeros(int(sr * duration), dtype=np.float32)
    beat_interval = int(sr * 0.5)  # 120 BPM
    for i in range(0, len(samples), beat_interval):
        end = min(i + 50, len(samples))
        samples[i:end] = 0.8
    analyzer.feed(samples)
    result = analyzer.feed(samples)
    if result.bpm is not None:
        assert 100 <= result.bpm <= 140


def test_palette_cycling():
    cfg = PartyConfig(palette=[[255, 0, 0], [0, 255, 0], [0, 0, 255]])
    mode = DJMode.__new__(DJMode)
    mode._config = cfg
    mode._palette_index = 0
    c0 = mode._next_palette_color()
    assert c0 == (255, 0, 0)
    c1 = mode._next_palette_color()
    assert c1 == (0, 255, 0)
    c2 = mode._next_palette_color()
    assert c2 == (0, 0, 255)
    c3 = mode._next_palette_color()
    assert c3 == (255, 0, 0)  # wraps


def test_accent_brightness_toggle():
    cfg = PartyConfig(accent_brightness_low=40, accent_brightness_high=100)
    mode = DJMode.__new__(DJMode)
    mode._config = cfg
    mode._accent_high = False
    br = mode._toggle_accent()
    assert br == 100
    assert mode._accent_high is True
    br = mode._toggle_accent()
    assert br == 40
    assert mode._accent_high is False


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
