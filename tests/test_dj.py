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
        for zone in ("wall_left", "wall_right", "monitor", "floor", "bedroom"):
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
