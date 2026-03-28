import asyncio
import pytest
from unittest.mock import MagicMock
from aether.lighting.ramp import ColorState
from aether.modes.focus import FocusMode, PomodoroPhase
from aether.config import FocusConfig


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


def make_focus(config=None, mixer=None):
    cfg = config or FocusConfig(work_min=1, short_break_min=1, long_break_min=1, cycles=2)
    mx = mixer or FakeMixer()
    cancel = asyncio.Event()
    pause = asyncio.Event()
    return FocusMode(cfg, mx, cancel, pause), mx, cancel


def test_initial_phase_is_work():
    mode, _, _ = make_focus()
    assert mode.phase == PomodoroPhase.WORK
    assert mode.cycle == 1


def test_advance_work_to_short_break():
    mode, _, _ = make_focus()
    mode._advance()
    assert mode.phase == PomodoroPhase.SHORT_BREAK


def test_advance_short_break_to_work():
    mode, _, _ = make_focus()
    mode._advance()  # work -> short_break
    mode._advance()  # short_break -> work (cycle 2)
    assert mode.phase == PomodoroPhase.WORK
    assert mode.cycle == 2


def test_advance_last_cycle_ends_with_long_break():
    cfg = FocusConfig(work_min=1, short_break_min=1, long_break_min=1, cycles=4)
    mode, _, _ = make_focus(config=cfg)
    # Simulate 4 full cycles: work, short, work, short, work, short, work, long
    for i in range(7):
        mode._advance()
    assert mode.phase == PomodoroPhase.LONG_BREAK


def test_advance_past_all_cycles_returns_done():
    cfg = FocusConfig(work_min=1, short_break_min=1, long_break_min=1, cycles=2)
    mode, _, _ = make_focus(config=cfg)
    # cycle 1: work -> short_break -> cycle 2: work -> short_break -> done
    mode._advance()  # short_break
    mode._advance()  # work (cycle 2)
    mode._advance()  # short_break
    done = mode._advance()  # done
    assert done is True


def test_rope_brightness_at_start():
    mode, _, _ = make_focus()
    assert mode._rope_brightness(0.0) == 10


def test_rope_brightness_at_end():
    mode, _, _ = make_focus()
    assert mode._rope_brightness(1.0) == 100


def test_rope_brightness_midpoint():
    mode, _, _ = make_focus()
    result = mode._rope_brightness(0.5)
    assert 50 <= result <= 60  # ~55


def test_apply_work_lighting():
    mode, mx, _ = make_focus()
    mode._apply_work_lighting(progress=0.0)
    # Monitor should get cool white
    monitor_subs = [(s, z, c, p) for s, z, c, p in mx.submissions if z == "monitor"]
    assert len(monitor_subs) == 1
    assert monitor_subs[0][2] == ColorState(r=255, g=255, b=255, brightness=100)
    # Floor and bedroom should be off
    floor_subs = [(s, z, c, p) for s, z, c, p in mx.submissions if z == "floor"]
    assert floor_subs[0][2] == ColorState(r=0, g=0, b=0, brightness=0)
    # Ropes should be at dim brightness
    rope_subs = [(s, z, c, p) for s, z, c, p in mx.submissions if z == "wall_left"]
    assert rope_subs[0][2].brightness == 10
    # All submissions should be priority 1
    assert all(p == 1 for _, _, _, p in mx.submissions)
