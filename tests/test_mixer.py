import time
import asyncio
import pytest
from aether.lighting.ramp import ColorState
from aether.mixer import Mixer, Claim


class FakeZoneManager:
    def __init__(self):
        self.calls: list[tuple[str, ColorState]] = []
        self.paused = False

    def set_zone(self, zone: str, state: ColorState) -> None:
        self.calls.append((zone, state))

    def get(self, zone: str) -> ColorState:
        return ColorState(r=0, g=0, b=0, brightness=0)


def test_submit_and_resolve():
    zm = FakeZoneManager()
    mixer = Mixer(zm)
    red = ColorState(r=255, g=0, b=0, brightness=100)
    mixer.submit("circadian", "floor", red, priority=2)
    mixer.resolve()
    assert len(zm.calls) == 1
    assert zm.calls[0] == ("floor", red)


def test_higher_priority_wins():
    zm = FakeZoneManager()
    mixer = Mixer(zm)
    red = ColorState(r=255, g=0, b=0, brightness=100)
    blue = ColorState(r=0, g=0, b=255, brightness=100)
    mixer.submit("circadian", "floor", red, priority=2)
    mixer.submit("voice", "floor", blue, priority=0)
    mixer.resolve()
    floor_calls = [c for c in zm.calls if c[0] == "floor"]
    assert floor_calls[-1][1] == blue


def test_release_falls_back():
    zm = FakeZoneManager()
    mixer = Mixer(zm)
    red = ColorState(r=255, g=0, b=0, brightness=100)
    blue = ColorState(r=0, g=0, b=255, brightness=100)
    mixer.submit("circadian", "floor", red, priority=2)
    mixer.submit("voice", "floor", blue, priority=0)
    mixer.resolve()
    zm.calls.clear()
    mixer.release("voice", "floor")
    mixer.resolve()
    floor_calls = [c for c in zm.calls if c[0] == "floor"]
    assert floor_calls[-1][1] == red


def test_release_all():
    zm = FakeZoneManager()
    mixer = Mixer(zm)
    blue = ColorState(r=0, g=0, b=255, brightness=100)
    red = ColorState(r=255, g=0, b=0, brightness=100)
    mixer.submit("focus", "floor", blue, priority=1)
    mixer.submit("focus", "monitor", blue, priority=1)
    mixer.submit("circadian", "floor", red, priority=2)
    mixer.submit("circadian", "monitor", red, priority=2)
    mixer.resolve()
    zm.calls.clear()
    mixer.release_all("focus")
    mixer.resolve()
    floor_calls = [c for c in zm.calls if c[0] == "floor"]
    monitor_calls = [c for c in zm.calls if c[0] == "monitor"]
    assert floor_calls[-1][1] == red
    assert monitor_calls[-1][1] == red


def test_submit_all_zones():
    zm = FakeZoneManager()
    mixer = Mixer(zm)
    white = ColorState(r=255, g=255, b=255, brightness=100)
    mixer.submit_all("circadian", white, priority=2)
    mixer.resolve()
    assert len(zm.calls) == 5


def test_ttl_expiry():
    zm = FakeZoneManager()
    mixer = Mixer(zm)
    red = ColorState(r=255, g=0, b=0, brightness=100)
    blue = ColorState(r=0, g=0, b=255, brightness=100)
    mixer.submit("circadian", "floor", red, priority=2)
    mixer.submit("voice", "floor", blue, priority=0, ttl_sec=0)
    mixer.expire_claims()
    mixer.resolve()
    floor_calls = [c for c in zm.calls if c[0] == "floor"]
    assert floor_calls[-1][1] == red


def test_get_active_claims():
    zm = FakeZoneManager()
    mixer = Mixer(zm)
    red = ColorState(r=255, g=0, b=0, brightness=100)
    mixer.submit("circadian", "floor", red, priority=2)
    mixer.resolve()
    claims = mixer.get_active_claims()
    assert "floor" in claims
    assert claims["floor"].source == "circadian"


def test_paused_skips_forwarding():
    zm = FakeZoneManager()
    zm.paused = True
    mixer = Mixer(zm)
    red = ColorState(r=255, g=0, b=0, brightness=100)
    mixer.submit("circadian", "floor", red, priority=2)
    mixer.resolve()
    assert len(zm.calls) == 0


def test_same_source_updates_claim():
    zm = FakeZoneManager()
    mixer = Mixer(zm)
    red = ColorState(r=255, g=0, b=0, brightness=100)
    blue = ColorState(r=0, g=0, b=255, brightness=100)
    mixer.submit("circadian", "floor", red, priority=2)
    mixer.submit("circadian", "floor", blue, priority=2)
    mixer.resolve()
    floor_calls = [c for c in zm.calls if c[0] == "floor"]
    assert floor_calls[-1][1] == blue
