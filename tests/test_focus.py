import asyncio
import pytest
from unittest.mock import MagicMock
from aether.lighting.ramp import ColorState
from aether.modes.focus import FocusMode, PomodoroPhase
from aether.config import FocusConfig


class FakeZoneManager:
    def __init__(self):
        self.calls: list[tuple[str, ColorState]] = []
        self.paused = False

    def set_zone(self, zone: str, state: ColorState) -> None:
        self.calls.append((zone, state))

    def set_all(self, state: ColorState) -> None:
        for zone in ("wall_left", "wall_right", "monitor", "floor", "bedroom"):
            self.set_zone(zone, state)


def make_focus(config=None, zones=None):
    cfg = config or FocusConfig(work_min=1, short_break_min=1, long_break_min=1, cycles=2)
    zm = zones or FakeZoneManager()
    cancel = asyncio.Event()
    pause = asyncio.Event()
    return FocusMode(cfg, zm, cancel, pause), zm, cancel


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
    mode, zm, _ = make_focus()
    mode._apply_work_lighting(progress=0.0)
    # Monitor should get cool white
    monitor_calls = [(z, c) for z, c in zm.calls if z == "monitor"]
    assert len(monitor_calls) == 1
    assert monitor_calls[0][1] == ColorState(r=255, g=255, b=255, brightness=100)
    # Floor and bedroom should be off
    floor_calls = [(z, c) for z, c in zm.calls if z == "floor"]
    assert floor_calls[0][1] == ColorState(r=0, g=0, b=0, brightness=0)
    # Ropes should be at dim brightness
    rope_calls = [(z, c) for z, c in zm.calls if z == "wall_left"]
    assert rope_calls[0][1].brightness == 10
