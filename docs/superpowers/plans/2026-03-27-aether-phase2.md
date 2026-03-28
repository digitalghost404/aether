# Aether Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add FOCUS (Pomodoro), PARTY (DJ Lightshow), and SLEEP (cascade shutdown) states to Aether, plus global pause/resume.

**Architecture:** Extend the existing `State` enum and transition table with three new states. Each state's behavior lives in a new `src/aether/modes/` package. The circadian engine delegates to mode coroutines when a non-PRESENT/AWAY state is active. A `paused` flag on ZoneManager suppresses all light output without stopping the daemon.

**Tech Stack:** Python 3.14, asyncio, librosa (new), pw-cat (PipeWire), existing paho-mqtt/Pydantic/Click stack.

**Spec:** `docs/superpowers/specs/2026-03-27-aether-phase2-design.md`

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `src/aether/modes/__init__.py` | Package init — exports mode classes |
| `src/aether/modes/focus.py` | Pomodoro timer, work/break cycling, rope brightness ramp |
| `src/aether/modes/dj.py` | PipeWire audio tap subprocess, librosa beat/onset analysis, accent + base lighting |
| `src/aether/modes/sleep.py` | Cascade shutdown coroutine with staged per-zone fading |
| `tests/test_focus.py` | Pomodoro timer cycling, brightness ramp math |
| `tests/test_sleep.py` | Cascade stage timing, cancel behavior |
| `tests/test_dj.py` | Beat detection with synthetic audio, rate budget |
| `tests/test_pause.py` | Pause/resume suppresses zone output, timers freeze |

### Modified Files

| File | Changes |
|------|---------|
| `src/aether/state.py` | Add FOCUS/PARTY/SLEEP states, 6 new events, extended transition table |
| `src/aether/config.py` | Add FocusConfig, PartyConfig, SleepConfig models |
| `src/aether/lighting/zones.py` | Add `paused` flag, per-zone set during pause suppression |
| `src/aether/cli.py` | Add focus/party/sleep/pause/resume commands, extend status, wire modes into daemon |
| `src/aether/vision/presence.py` | Suppress absence timer in FOCUS/PARTY states |
| `config.example.yaml` | Add focus/party/sleep config sections |
| `pyproject.toml` | Add `librosa` dependency |

---

### Task 1: Extend State Machine

**Files:**
- Modify: `src/aether/state.py`
- Modify: `tests/test_state.py`

- [ ] **Step 1: Write failing tests for new states and transitions**

Add to `tests/test_state.py`:

```python
def test_present_to_focus():
    transitions = []
    sm = StateMachine(on_transition=lambda t: transitions.append(t))
    sm.handle_event(Event.FOCUS_START)
    assert sm.state == State.FOCUS
    assert len(transitions) == 1
    assert transitions[0].from_state == State.PRESENT
    assert transitions[0].to_state == State.FOCUS


def test_focus_to_present():
    sm = StateMachine()
    sm.handle_event(Event.FOCUS_START)
    sm.handle_event(Event.FOCUS_STOP)
    assert sm.state == State.PRESENT


def test_present_to_party():
    sm = StateMachine()
    sm.handle_event(Event.PARTY_START)
    assert sm.state == State.PARTY


def test_party_to_present():
    sm = StateMachine()
    sm.handle_event(Event.PARTY_START)
    sm.handle_event(Event.PARTY_STOP)
    assert sm.state == State.PRESENT


def test_present_to_sleep():
    sm = StateMachine()
    sm.handle_event(Event.SLEEP_START)
    assert sm.state == State.SLEEP


def test_sleep_cancel_to_present():
    sm = StateMachine()
    sm.handle_event(Event.SLEEP_START)
    sm.handle_event(Event.SLEEP_CANCEL)
    assert sm.state == State.PRESENT


def test_sleep_complete_to_away():
    sm = StateMachine()
    sm.handle_event(Event.SLEEP_START)
    sm.handle_event(Event.SLEEP_COMPLETE)
    assert sm.state == State.AWAY


def test_away_cannot_enter_focus():
    sm = StateMachine()
    sm.handle_event(Event.HUMAN_ABSENT)
    assert sm.state == State.AWAY
    result = sm.handle_event(Event.FOCUS_START)
    assert result is None
    assert sm.state == State.AWAY


def test_away_cannot_enter_party():
    sm = StateMachine()
    sm.handle_event(Event.HUMAN_ABSENT)
    result = sm.handle_event(Event.PARTY_START)
    assert result is None
    assert sm.state == State.AWAY


def test_away_cannot_enter_sleep():
    sm = StateMachine()
    sm.handle_event(Event.HUMAN_ABSENT)
    result = sm.handle_event(Event.SLEEP_START)
    assert result is None
    assert sm.state == State.AWAY


def test_focus_cannot_enter_party():
    sm = StateMachine()
    sm.handle_event(Event.FOCUS_START)
    result = sm.handle_event(Event.PARTY_START)
    assert result is None
    assert sm.state == State.FOCUS


def test_focus_ignores_human_absent():
    sm = StateMachine()
    sm.handle_event(Event.FOCUS_START)
    result = sm.handle_event(Event.HUMAN_ABSENT)
    assert result is None
    assert sm.state == State.FOCUS


def test_party_ignores_human_absent():
    sm = StateMachine()
    sm.handle_event(Event.PARTY_START)
    result = sm.handle_event(Event.HUMAN_ABSENT)
    assert result is None
    assert sm.state == State.PARTY
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/digitalghost/projects/aether && .venv/bin/pytest tests/test_state.py -v`
Expected: FAIL — `Event` has no attribute `FOCUS_START`, etc.

- [ ] **Step 3: Implement state machine extensions**

Replace `src/aether/state.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Callable


class State(Enum):
    PRESENT = "present"
    AWAY = "away"
    FOCUS = "focus"
    PARTY = "party"
    SLEEP = "sleep"


class Event(Enum):
    HUMAN_DETECTED = "human_detected"
    HUMAN_ABSENT = "human_absent"
    FOCUS_START = "focus_start"
    FOCUS_STOP = "focus_stop"
    PARTY_START = "party_start"
    PARTY_STOP = "party_stop"
    SLEEP_START = "sleep_start"
    SLEEP_CANCEL = "sleep_cancel"
    SLEEP_COMPLETE = "sleep_complete"


@dataclass(frozen=True)
class Transition:
    from_state: State
    to_state: State
    reason: str
    timestamp: datetime


TRANSITION_TABLE: dict[tuple[State, Event], State] = {
    # Phase 1
    (State.PRESENT, Event.HUMAN_ABSENT): State.AWAY,
    (State.AWAY, Event.HUMAN_DETECTED): State.PRESENT,
    # Phase 2 — FOCUS
    (State.PRESENT, Event.FOCUS_START): State.FOCUS,
    (State.FOCUS, Event.FOCUS_STOP): State.PRESENT,
    # Phase 2 — PARTY
    (State.PRESENT, Event.PARTY_START): State.PARTY,
    (State.PARTY, Event.PARTY_STOP): State.PRESENT,
    # Phase 2 — SLEEP
    (State.PRESENT, Event.SLEEP_START): State.SLEEP,
    (State.SLEEP, Event.SLEEP_CANCEL): State.PRESENT,
    (State.SLEEP, Event.SLEEP_COMPLETE): State.AWAY,
}


class InvalidTransition(Exception):
    pass


class StateMachine:
    def __init__(self, on_transition: Callable[[Transition], None] | None = None):
        self.state = State.PRESENT
        self._on_transition = on_transition

    def handle_event(self, event: Event) -> Transition | None:
        key = (self.state, event)
        new_state = TRANSITION_TABLE.get(key)

        if new_state is None:
            return None

        transition = Transition(
            from_state=self.state,
            to_state=new_state,
            reason=event.value,
            timestamp=datetime.now(timezone.utc),
        )
        self.state = new_state

        if self._on_transition:
            self._on_transition(transition)

        return transition
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/digitalghost/projects/aether && .venv/bin/pytest tests/test_state.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
cd /home/digitalghost/projects/aether
git add src/aether/state.py tests/test_state.py
git commit -m "feat: extend state machine with FOCUS, PARTY, SLEEP states"
```

---

### Task 2: Add Config Models

**Files:**
- Modify: `src/aether/config.py`
- Modify: `config.example.yaml`

- [ ] **Step 1: Write failing test for new config sections**

Create `tests/test_config_phase2.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/digitalghost/projects/aether && .venv/bin/pytest tests/test_config_phase2.py -v`
Expected: FAIL — `FocusConfig` not importable

- [ ] **Step 3: Add new config models to config.py**

Add after `AlertsConfig` class (line 65) in `src/aether/config.py`:

```python
class FocusConfig(BaseModel):
    work_min: int = 25
    short_break_min: int = 5
    long_break_min: int = 15
    cycles: int = 4
    work_color: list[int] = [255, 255, 255]
    work_brightness: int = 100
    rope_dim_brightness: int = 10
    break_color: list[int] = [180, 230, 180]
    break_brightness: int = 10


class PartyConfig(BaseModel):
    accent_zone: str = "floor"
    accent_brightness_low: int = 40
    accent_brightness_high: int = 100
    base_shift_beats: int = 8
    silence_timeout_sec: int = 120
    palette: list[list[int]] = [
        [180, 50, 255],
        [255, 50, 150],
        [50, 220, 220],
        [255, 80, 50],
    ]


class SleepConfig(BaseModel):
    total_duration_min: int = 5
    bedroom_final_color: list[int] = [200, 100, 30]
    bedroom_final_brightness: int = 5
```

Add to `AetherConfig` class (after `alerts` field):

```python
class AetherConfig(BaseModel):
    location: LocationConfig = LocationConfig()
    presence: PresenceConfig = PresenceConfig()
    mqtt: MqttConfig = MqttConfig()
    circadian: CircadianConfig = CircadianConfig()
    zones: dict[str, ZoneConfig] = {}
    alerts: AlertsConfig = AlertsConfig()
    focus: FocusConfig = FocusConfig()
    party: PartyConfig = PartyConfig()
    sleep: SleepConfig = SleepConfig()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/digitalghost/projects/aether && .venv/bin/pytest tests/test_config_phase2.py -v`
Expected: All PASS

- [ ] **Step 5: Update config.example.yaml**

Append to `config.example.yaml` after the `alerts` section:

```yaml

focus:
  work_min: 25
  short_break_min: 5
  long_break_min: 15
  cycles: 4                          # 0 = indefinite
  work_color: [255, 255, 255]        # cool white for monitor
  work_brightness: 100
  rope_dim_brightness: 10
  break_color: [180, 230, 180]       # green-warm for breaks
  break_brightness: 10

party:
  accent_zone: floor                 # which light pulses on beats
  accent_brightness_low: 40
  accent_brightness_high: 100
  base_shift_beats: 8                # color change every N beats
  silence_timeout_sec: 120
  palette:
    - [180, 50, 255]                 # purple
    - [255, 50, 150]                 # magenta
    - [50, 220, 220]                 # teal
    - [255, 80, 50]                  # hot orange

sleep:
  total_duration_min: 5
  bedroom_final_color: [200, 100, 30]
  bedroom_final_brightness: 5
```

- [ ] **Step 6: Commit**

```bash
cd /home/digitalghost/projects/aether
git add src/aether/config.py config.example.yaml tests/test_config_phase2.py
git commit -m "feat: add Focus, Party, Sleep config models"
```

---

### Task 3: Add Pause/Resume to ZoneManager

**Files:**
- Modify: `src/aether/lighting/zones.py`
- Create: `tests/test_pause.py`

- [ ] **Step 1: Write failing tests for pause behavior**

Create `tests/test_pause.py`:

```python
from aether.lighting.zones import ZoneManager
from aether.lighting.ramp import ColorState


class FakeAdapter:
    def __init__(self):
        self.published = []

    def publish_zone(self, zone: str, color: dict):
        self.published.append((zone, color))


def test_set_zone_publishes_when_not_paused():
    adapter = FakeAdapter()
    zm = ZoneManager(adapter)
    color = ColorState(r=255, g=0, b=0, brightness=100)
    zm.set_zone("floor", color)
    assert len(adapter.published) == 1
    assert adapter.published[0] == ("floor", color.to_dict())


def test_set_zone_suppressed_when_paused():
    adapter = FakeAdapter()
    zm = ZoneManager(adapter)
    zm.paused = True
    color = ColorState(r=255, g=0, b=0, brightness=100)
    zm.set_zone("floor", color)
    assert len(adapter.published) == 0


def test_resume_does_not_replay_suppressed():
    adapter = FakeAdapter()
    zm = ZoneManager(adapter)
    zm.paused = True
    color = ColorState(r=255, g=0, b=0, brightness=100)
    zm.set_zone("floor", color)
    zm.paused = False
    # No automatic replay — caller is responsible for re-applying state
    assert len(adapter.published) == 0


def test_current_state_tracks_even_when_paused():
    adapter = FakeAdapter()
    zm = ZoneManager(adapter)
    zm.paused = True
    color = ColorState(r=255, g=0, b=0, brightness=100)
    zm.set_zone("floor", color)
    # Internal state still updated for resume logic
    assert zm.get("floor") == color
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/digitalghost/projects/aether && .venv/bin/pytest tests/test_pause.py -v`
Expected: FAIL — `ZoneManager` has no attribute `paused`

- [ ] **Step 3: Add pause flag to ZoneManager**

Replace `src/aether/lighting/zones.py`:

```python
from __future__ import annotations

from aether.lighting.ramp import ColorState


class ZoneManager:
    ZONE_NAMES = ("wall_left", "wall_right", "monitor", "floor", "bedroom")

    def __init__(self, govee_adapter):
        self._adapter = govee_adapter
        self._current: dict[str, ColorState] = {
            name: ColorState(r=0, g=0, b=0, brightness=0) for name in self.ZONE_NAMES
        }
        self.paused: bool = False

    def get(self, zone: str) -> ColorState:
        return self._current[zone]

    def set_zone(self, zone: str, state: ColorState) -> None:
        if self._current[zone] == state:
            return  # Skip duplicate — avoid hammering Govee API
        self._current[zone] = state
        if not self.paused:
            self._adapter.publish_zone(zone, state.to_dict())

    def set_all(self, state: ColorState) -> None:
        for zone in self.ZONE_NAMES:
            self.set_zone(zone, state)

    def get_all(self) -> dict[str, ColorState]:
        return dict(self._current)

    def flush_current(self) -> None:
        """Re-publish all current zone states. Call after resume."""
        for zone, state in self._current.items():
            self._adapter.publish_zone(zone, state.to_dict())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/digitalghost/projects/aether && .venv/bin/pytest tests/test_pause.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
cd /home/digitalghost/projects/aether
git add src/aether/lighting/zones.py tests/test_pause.py
git commit -m "feat: add pause/resume support to ZoneManager"
```

---

### Task 4: Implement FOCUS Mode

**Files:**
- Create: `src/aether/modes/__init__.py`
- Create: `src/aether/modes/focus.py`
- Create: `tests/test_focus.py`

- [ ] **Step 1: Create modes package**

Create `src/aether/modes/__init__.py`:

```python
from aether.modes.focus import FocusMode
```

(This will fail to import until focus.py exists — that's fine, we build it next.)

- [ ] **Step 2: Write failing tests for FocusMode**

Create `tests/test_focus.py`:

```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /home/digitalghost/projects/aether && .venv/bin/pytest tests/test_focus.py -v`
Expected: FAIL — `cannot import FocusMode`

- [ ] **Step 4: Implement FocusMode**

Create `src/aether/modes/focus.py`:

```python
from __future__ import annotations

import asyncio
import sys
from enum import Enum

from aether.config import FocusConfig
from aether.lighting.ramp import ColorState


class PomodoroPhase(Enum):
    WORK = "work"
    SHORT_BREAK = "short_break"
    LONG_BREAK = "long_break"


class FocusMode:
    def __init__(
        self,
        config: FocusConfig,
        zones,
        cancel: asyncio.Event,
        pause: asyncio.Event,
    ):
        self._config = config
        self._zones = zones
        self._cancel = cancel
        self._pause = pause
        self.phase = PomodoroPhase.WORK
        self.cycle = 1
        self._total_cycles = config.cycles
        self._work_in_cycle = 0  # 0 = on work, 1 = on break within cycle

    def _advance(self) -> bool:
        """Advance to next phase. Returns True if all cycles complete."""
        if self.phase == PomodoroPhase.WORK:
            # After work, go to break
            if self._total_cycles > 0 and self.cycle >= self._total_cycles:
                self.phase = PomodoroPhase.LONG_BREAK
            else:
                self.phase = PomodoroPhase.SHORT_BREAK
        elif self.phase in (PomodoroPhase.SHORT_BREAK, PomodoroPhase.LONG_BREAK):
            if self.phase == PomodoroPhase.LONG_BREAK:
                return True  # All cycles done
            # After break, next work cycle
            self.cycle += 1
            if self._total_cycles > 0 and self.cycle > self._total_cycles:
                return True  # All cycles done
            self.phase = PomodoroPhase.WORK
        return False

    def _rope_brightness(self, progress: float) -> int:
        """Linear interpolation from rope_dim_brightness to 100."""
        dim = self._config.rope_dim_brightness
        return round(dim + (100 - dim) * progress)

    def _apply_work_lighting(self, progress: float) -> None:
        cfg = self._config
        # Monitor: locked cool white
        self._zones.set_zone(
            "monitor",
            ColorState(r=cfg.work_color[0], g=cfg.work_color[1], b=cfg.work_color[2], brightness=cfg.work_brightness),
        )
        # Ropes: dim warm with brightness ramp
        rope_br = self._rope_brightness(progress)
        rope_color = ColorState(r=180, g=140, b=60, brightness=rope_br)
        self._zones.set_zone("wall_left", rope_color)
        self._zones.set_zone("wall_right", rope_color)
        # Floor + bedroom: off
        off = ColorState(r=0, g=0, b=0, brightness=0)
        self._zones.set_zone("floor", off)
        self._zones.set_zone("bedroom", off)

    def _apply_break_lighting(self) -> None:
        cfg = self._config
        # Monitor: dimmed
        self._zones.set_zone(
            "monitor",
            ColorState(r=cfg.work_color[0], g=cfg.work_color[1], b=cfg.work_color[2], brightness=60),
        )
        # Ropes: break color at break brightness
        break_color = ColorState(
            r=cfg.break_color[0], g=cfg.break_color[1], b=cfg.break_color[2],
            brightness=cfg.break_brightness,
        )
        self._zones.set_zone("wall_left", break_color)
        self._zones.set_zone("wall_right", break_color)
        # Floor + bedroom: still off
        off = ColorState(r=0, g=0, b=0, brightness=0)
        self._zones.set_zone("floor", off)
        self._zones.set_zone("bedroom", off)

    def _apply_long_break_lighting(self) -> None:
        # Monitor: dimmed
        cfg = self._config
        self._zones.set_zone(
            "monitor",
            ColorState(r=cfg.work_color[0], g=cfg.work_color[1], b=cfg.work_color[2], brightness=60),
        )
        # Ropes: relaxed amber at 70%
        amber = ColorState(r=255, g=180, b=60, brightness=70)
        self._zones.set_zone("wall_left", amber)
        self._zones.set_zone("wall_right", amber)
        off = ColorState(r=0, g=0, b=0, brightness=0)
        self._zones.set_zone("floor", off)
        self._zones.set_zone("bedroom", off)

    async def _flash_ropes(self, count: int = 2) -> None:
        bright = ColorState(r=255, g=255, b=255, brightness=100)
        dim = ColorState(r=180, g=140, b=60, brightness=self._config.rope_dim_brightness)
        for _ in range(count):
            self._zones.set_zone("wall_left", bright)
            self._zones.set_zone("wall_right", bright)
            await asyncio.sleep(0.3)
            self._zones.set_zone("wall_left", dim)
            self._zones.set_zone("wall_right", dim)
            await asyncio.sleep(0.3)

    async def _wait_with_pause(self, seconds: float) -> bool:
        """Sleep for `seconds`, respecting pause and cancel. Returns True if cancelled."""
        remaining = seconds
        while remaining > 0:
            if self._cancel.is_set():
                return True
            if self._pause.is_set():
                await asyncio.sleep(0.5)
                continue
            step = min(1.0, remaining)
            await asyncio.sleep(step)
            remaining -= step
        return self._cancel.is_set()

    async def _run_work(self) -> bool:
        """Run a work period with rope brightness ramp. Returns True if cancelled."""
        total_sec = self._config.work_min * 60
        elapsed = 0.0
        tick = 30.0  # Update lighting every 30s

        print(f"[aether] FOCUS: work period {self.cycle}/{self._total_cycles or '∞'} ({self._config.work_min}min)", file=sys.stderr)

        while elapsed < total_sec:
            if self._cancel.is_set():
                return True
            if self._pause.is_set():
                await asyncio.sleep(0.5)
                continue

            progress = elapsed / total_sec
            self._apply_work_lighting(progress)

            step = min(tick, total_sec - elapsed)
            await asyncio.sleep(step)
            elapsed += step

        # Final: ropes at 100%
        self._apply_work_lighting(1.0)
        return False

    async def _run_break(self, is_long: bool) -> bool:
        """Run a break period. Returns True if cancelled."""
        minutes = self._config.long_break_min if is_long else self._config.short_break_min
        label = "long break" if is_long else "short break"
        print(f"[aether] FOCUS: {label} ({minutes}min)", file=sys.stderr)

        await self._flash_ropes(count=2)

        if is_long:
            self._apply_long_break_lighting()
        else:
            self._apply_break_lighting()

        cancelled = await self._wait_with_pause(minutes * 60)
        if cancelled:
            return True

        await self._flash_ropes(count=2)
        return False

    async def run(self) -> None:
        """Main focus mode loop. Runs until cancelled or all cycles complete."""
        try:
            while True:
                if self.phase == PomodoroPhase.WORK:
                    cancelled = await self._run_work()
                    if cancelled:
                        return
                    done = self._advance()
                    if done:
                        return
                elif self.phase == PomodoroPhase.SHORT_BREAK:
                    cancelled = await self._run_break(is_long=False)
                    if cancelled:
                        return
                    done = self._advance()
                    if done:
                        return
                elif self.phase == PomodoroPhase.LONG_BREAK:
                    cancelled = await self._run_break(is_long=True)
                    if cancelled:
                        return
                    done = self._advance()
                    if done:
                        return
        finally:
            print("[aether] FOCUS: ended", file=sys.stderr)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/digitalghost/projects/aether && .venv/bin/pytest tests/test_focus.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
cd /home/digitalghost/projects/aether
git add src/aether/modes/__init__.py src/aether/modes/focus.py tests/test_focus.py
git commit -m "feat: implement FOCUS mode with Pomodoro timer and rope brightness ramp"
```

---

### Task 5: Implement SLEEP Mode

**Files:**
- Create: `src/aether/modes/sleep.py`
- Create: `tests/test_sleep.py`

- [ ] **Step 1: Write failing tests for SleepMode**

Create `tests/test_sleep.py`:

```python
import asyncio
import pytest
from aether.lighting.ramp import ColorState
from aether.modes.sleep import SleepMode, SleepStage
from aether.config import SleepConfig


class FakeZoneManager:
    def __init__(self):
        self.calls: list[tuple[str, ColorState]] = []
        self.paused = False

    def set_zone(self, zone: str, state: ColorState) -> None:
        self.calls.append((zone, state))

    def get(self, zone: str) -> ColorState:
        return ColorState(r=255, g=255, b=255, brightness=100)


class FakeMqtt:
    def __init__(self):
        self.published: list[tuple[str, str]] = []

    def publish(self, topic: str, payload, retain: bool = False) -> None:
        self.published.append((topic, payload))


def make_sleep(duration_min=1):
    cfg = SleepConfig(total_duration_min=duration_min, bedroom_final_color=[200, 100, 30], bedroom_final_brightness=5)
    zm = FakeZoneManager()
    mqtt = FakeMqtt()
    cancel = asyncio.Event()
    pause = asyncio.Event()
    return SleepMode(cfg, zm, mqtt, cancel, pause), zm, mqtt, cancel


def test_initial_stage():
    mode, _, _, _ = make_sleep()
    assert mode.stage == SleepStage.MONITOR


def test_stages_sequence():
    stages = list(SleepStage)
    assert stages == [
        SleepStage.MONITOR,
        SleepStage.ROPES,
        SleepStage.FLOOR,
        SleepStage.BEDROOM,
        SleepStage.COMPLETE,
    ]


def test_stage_time_fractions_sum_to_one():
    mode, _, _, _ = make_sleep()
    total = sum(mode.STAGE_FRACTIONS.values())
    assert abs(total - 1.0) < 0.01


@pytest.mark.asyncio
async def test_cancel_stops_cascade():
    mode, zm, _, cancel = make_sleep()
    cancel.set()
    await mode.run()
    # Should exit quickly without completing
    assert mode.stage == SleepStage.MONITOR


@pytest.mark.asyncio
async def test_full_cascade_reaches_complete():
    """Use a very short duration to test full cascade."""
    cfg = SleepConfig(total_duration_min=0, bedroom_final_color=[200, 100, 30], bedroom_final_brightness=5)
    zm = FakeZoneManager()
    mqtt = FakeMqtt()
    cancel = asyncio.Event()
    pause = asyncio.Event()
    mode = SleepMode(cfg, zm, mqtt, cancel, pause)
    mode.STAGE_FRACTIONS = {s: 0.0 for s in SleepStage if s != SleepStage.COMPLETE}
    mode.STAGE_FRACTIONS[SleepStage.COMPLETE] = 0.0
    await mode.run()
    assert mode.completed
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/digitalghost/projects/aether && .venv/bin/pytest tests/test_sleep.py -v`
Expected: FAIL — `cannot import SleepMode`

- [ ] **Step 3: Implement SleepMode**

Create `src/aether/modes/sleep.py`:

```python
from __future__ import annotations

import asyncio
import sys
from enum import Enum

from aether.config import SleepConfig
from aether.lighting.ramp import ColorState, generate_ramp


class SleepStage(Enum):
    MONITOR = "monitor"
    ROPES = "ropes"
    FLOOR = "floor"
    BEDROOM = "bedroom"
    COMPLETE = "complete"


class SleepMode:
    # Fraction of total_duration_min spent on each stage
    STAGE_FRACTIONS: dict[SleepStage, float] = {
        SleepStage.MONITOR: 0.10,    # 30s of 5min
        SleepStage.ROPES: 0.40,      # 2min of 5min
        SleepStage.FLOOR: 0.20,      # 1min of 5min
        SleepStage.BEDROOM: 0.30,    # 1.5min of 5min
    }

    def __init__(
        self,
        config: SleepConfig,
        zones,
        mqtt,
        cancel: asyncio.Event,
        pause: asyncio.Event,
    ):
        self._config = config
        self._zones = zones
        self._mqtt = mqtt
        self._cancel = cancel
        self._pause = pause
        self.stage = SleepStage.MONITOR
        self.completed = False

    def _publish_stage(self, stage: SleepStage) -> None:
        self._mqtt.publish("aether/sleep/stage", f'"{stage.value}"', retain=True)

    async def _fade_zone(self, zone: str, target: ColorState, duration_sec: float) -> bool:
        """Fade a zone to target over duration. Returns True if cancelled."""
        start = self._zones.get(zone)
        if duration_sec <= 0:
            self._zones.set_zone(zone, target)
            return self._cancel.is_set()

        # Use ~1 update per 10-15 seconds to stay within rate limits
        step_count = max(1, int(duration_sec / 12))
        interval = duration_sec / step_count

        for step in generate_ramp(start, target, duration_sec, int(interval * 1000)):
            if self._cancel.is_set():
                return True
            while self._pause.is_set():
                await asyncio.sleep(0.5)
                if self._cancel.is_set():
                    return True
            self._zones.set_zone(zone, step)
            await asyncio.sleep(interval)

        self._zones.set_zone(zone, target)
        return False

    async def run(self) -> None:
        """Run the cascade shutdown. Sets self.completed = True when done."""
        total_sec = self._config.total_duration_min * 60
        off = ColorState(r=0, g=0, b=0, brightness=0)

        try:
            # Stage 1: Monitor fade to off
            self.stage = SleepStage.MONITOR
            self._publish_stage(self.stage)
            print("[aether] SLEEP: fading monitor", file=sys.stderr)
            dur = total_sec * self.STAGE_FRACTIONS[SleepStage.MONITOR]
            if await self._fade_zone("monitor", off, dur):
                return

            # Stage 2: Ropes fade to off
            self.stage = SleepStage.ROPES
            self._publish_stage(self.stage)
            print("[aether] SLEEP: fading ropes", file=sys.stderr)
            dur = total_sec * self.STAGE_FRACTIONS[SleepStage.ROPES]
            # Fade through warm amber first, then to off
            warm = ColorState(r=255, g=180, b=60, brightness=30)
            half = dur / 2
            if await self._fade_zone("wall_left", warm, half):
                return
            if await self._fade_zone("wall_right", warm, half):
                return
            if await self._fade_zone("wall_left", off, half):
                return
            if await self._fade_zone("wall_right", off, half):
                return

            # Stage 3: Floor lamp fade to off
            self.stage = SleepStage.FLOOR
            self._publish_stage(self.stage)
            print("[aether] SLEEP: fading floor lamp", file=sys.stderr)
            dur = total_sec * self.STAGE_FRACTIONS[SleepStage.FLOOR]
            nightlight = ColorState(r=180, g=140, b=60, brightness=10)
            if await self._fade_zone("floor", nightlight, dur * 0.6):
                return
            if await self._fade_zone("floor", off, dur * 0.4):
                return

            # Stage 4: Bedroom lamp fade to deep orange then off
            self.stage = SleepStage.BEDROOM
            self._publish_stage(self.stage)
            print("[aether] SLEEP: fading bedroom lamp", file=sys.stderr)
            dur = total_sec * self.STAGE_FRACTIONS[SleepStage.BEDROOM]
            cfg = self._config
            deep_orange = ColorState(
                r=cfg.bedroom_final_color[0],
                g=cfg.bedroom_final_color[1],
                b=cfg.bedroom_final_color[2],
                brightness=cfg.bedroom_final_brightness,
            )
            if await self._fade_zone("bedroom", deep_orange, dur * 0.8):
                return
            if await self._fade_zone("bedroom", off, dur * 0.2):
                return

            # Complete
            self.stage = SleepStage.COMPLETE
            self._publish_stage(self.stage)
            self.completed = True
            print("[aether] SLEEP: cascade complete", file=sys.stderr)

        except Exception as e:
            print(f"[aether] SLEEP error: {e}", file=sys.stderr)
```

- [ ] **Step 4: Update modes __init__.py**

Replace `src/aether/modes/__init__.py`:

```python
from aether.modes.focus import FocusMode
from aether.modes.sleep import SleepMode
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/digitalghost/projects/aether && .venv/bin/pytest tests/test_sleep.py tests/test_focus.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
cd /home/digitalghost/projects/aether
git add src/aether/modes/sleep.py src/aether/modes/__init__.py tests/test_sleep.py
git commit -m "feat: implement SLEEP mode with cascade shutdown sequence"
```

---

### Task 6: Implement PARTY Mode (DJ Lightshow)

**Files:**
- Create: `src/aether/modes/dj.py`
- Create: `tests/test_dj.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Add librosa dependency**

In `pyproject.toml`, add `"librosa"` to the `dependencies` list:

```toml
dependencies = [
    "mediapipe>=0.10",
    "opencv-python-headless",
    "paho-mqtt>=2.0",
    "pydantic>=2.0",
    "pyyaml>=6.0",
    "httpx",
    "click",
    "librosa",
]
```

- [ ] **Step 2: Install the new dependency**

Run: `cd /home/digitalghost/projects/aether && .venv/bin/pip install librosa`

- [ ] **Step 3: Write failing tests for DJMode**

Create `tests/test_dj.py`:

```python
import asyncio
import numpy as np
import pytest
from aether.lighting.ramp import ColorState
from aether.modes.dj import DJMode, BeatAnalyzer
from aether.config import PartyConfig


class FakeZoneManager:
    def __init__(self):
        self.calls: list[tuple[str, ColorState]] = []
        self.paused = False

    def set_zone(self, zone: str, state: ColorState) -> None:
        self.calls.append((zone, state))

    def get(self, zone: str) -> ColorState:
        return ColorState(r=128, g=128, b=128, brightness=50)


class FakeMqtt:
    def __init__(self):
        self.published = []

    def publish(self, topic: str, payload, retain: bool = False) -> None:
        self.published.append((topic, payload))


def test_beat_analyzer_detects_onset_in_loud_audio():
    analyzer = BeatAnalyzer(sr=22050)
    # Generate a click/impulse signal — should detect onset
    silence = np.zeros(22050, dtype=np.float32)
    click = np.zeros(22050, dtype=np.float32)
    click[0:100] = 1.0  # loud impulse at start
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
    # Generate 120 BPM click track (click every 0.5s)
    sr = 22050
    duration = 4.0  # 4 seconds of audio
    samples = np.zeros(int(sr * duration), dtype=np.float32)
    beat_interval = int(sr * 0.5)  # 120 BPM
    for i in range(0, len(samples), beat_interval):
        end = min(i + 50, len(samples))
        samples[i:end] = 0.8
    # Feed enough audio for BPM detection
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
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd /home/digitalghost/projects/aether && .venv/bin/pytest tests/test_dj.py -v`
Expected: FAIL — `cannot import DJMode`

- [ ] **Step 5: Implement DJMode**

Create `src/aether/modes/dj.py`:

```python
from __future__ import annotations

import asyncio
import subprocess
import sys
import time
from dataclasses import dataclass

import numpy as np

from aether.config import PartyConfig
from aether.lighting.ramp import ColorState


SAMPLE_RATE = 22050
CHUNK_DURATION = 1.0  # seconds per audio chunk
CHUNK_SAMPLES = int(SAMPLE_RATE * CHUNK_DURATION)


@dataclass
class AnalysisResult:
    energy: float
    is_onset: bool
    bpm: float | None


class BeatAnalyzer:
    def __init__(self, sr: int = SAMPLE_RATE):
        self._sr = sr
        self._energy_history: list[float] = []
        self._onset_threshold = 1.5
        self._audio_buffer: list[np.ndarray] = []

    def feed(self, samples: np.ndarray) -> AnalysisResult:
        import librosa

        energy = float(np.sqrt(np.mean(samples ** 2)))
        self._energy_history.append(energy)
        if len(self._energy_history) > 30:
            self._energy_history.pop(0)

        # Onset detection: energy spike above rolling average
        avg = np.mean(self._energy_history) if self._energy_history else 0.0
        is_onset = energy > avg * self._onset_threshold and energy > 0.01

        # BPM detection: accumulate audio and estimate periodically
        self._audio_buffer.append(samples)
        bpm = None
        total_samples = sum(len(b) for b in self._audio_buffer)
        if total_samples >= self._sr * 4:  # Need at least 4 seconds
            full_audio = np.concatenate(self._audio_buffer)
            try:
                tempo, _ = librosa.beat.beat_track(y=full_audio, sr=self._sr)
                bpm = float(np.asarray(tempo).flat[0])
            except Exception:
                pass
            # Keep last 8 seconds
            keep_samples = self._sr * 8
            if len(full_audio) > keep_samples:
                self._audio_buffer = [full_audio[-keep_samples:]]

        return AnalysisResult(energy=energy, is_onset=is_onset, bpm=bpm)


class DJMode:
    def __init__(
        self,
        config: PartyConfig,
        zones,
        mqtt,
        cancel: asyncio.Event,
        pause: asyncio.Event,
    ):
        self._config = config
        self._zones = zones
        self._mqtt = mqtt
        self._cancel = cancel
        self._pause = pause
        self._analyzer = BeatAnalyzer()
        self._palette_index = 0
        self._accent_high = False
        self._beats_since_shift = 0
        self._current_base_color: tuple[int, int, int] = config.palette[0] if config.palette else (128, 0, 255)
        self._last_sound_time = time.monotonic()

    def _next_palette_color(self) -> tuple[int, int, int]:
        palette = self._config.palette
        color = tuple(palette[self._palette_index])
        self._palette_index = (self._palette_index + 1) % len(palette)
        return color

    def _toggle_accent(self) -> int:
        self._accent_high = not self._accent_high
        if self._accent_high:
            return self._config.accent_brightness_high
        return self._config.accent_brightness_low

    def _apply_base_color(self, r: int, g: int, b: int, brightness: int = 80) -> None:
        color = ColorState(r=r, g=g, b=b, brightness=brightness)
        for zone in ("wall_left", "wall_right", "monitor", "bedroom"):
            self._zones.set_zone(zone, color)

    def _apply_accent(self, brightness: int) -> None:
        r, g, b = self._current_base_color
        accent = ColorState(r=r, g=g, b=b, brightness=brightness)
        self._zones.set_zone(self._config.accent_zone, accent)

    async def run(self) -> None:
        proc = None
        try:
            proc = subprocess.Popen(
                [
                    "pw-cat", "--record",
                    "--target", "@DEFAULT_AUDIO_SINK@",
                    "--format", "f32",
                    "--rate", str(SAMPLE_RATE),
                    "--channels", "1",
                    "-",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            print("[aether] PARTY: PipeWire audio tap started", file=sys.stderr)
        except FileNotFoundError:
            print("[aether] PARTY: pw-cat not found. Is PipeWire installed?", file=sys.stderr)
            return
        except Exception as e:
            print(f"[aether] PARTY: failed to start audio tap: {e}", file=sys.stderr)
            return

        # Apply initial base color
        r, g, b = self._current_base_color
        self._apply_base_color(r, g, b)
        self._apply_accent(self._config.accent_brightness_low)
        self._last_sound_time = time.monotonic()

        try:
            while not self._cancel.is_set():
                if self._pause.is_set():
                    await asyncio.sleep(0.5)
                    continue

                # Read audio chunk
                raw = await asyncio.to_thread(
                    proc.stdout.read, CHUNK_SAMPLES * 4  # float32 = 4 bytes
                )
                if not raw:
                    break

                samples = np.frombuffer(raw, dtype=np.float32)
                if len(samples) == 0:
                    continue

                result = self._analyzer.feed(samples)

                # Track silence for timeout
                if result.energy > 0.01:
                    self._last_sound_time = time.monotonic()
                elif time.monotonic() - self._last_sound_time > self._config.silence_timeout_sec:
                    print("[aether] PARTY: silence timeout, exiting", file=sys.stderr)
                    return

                # Accent pulse on onset
                if result.is_onset:
                    br = self._toggle_accent()
                    self._apply_accent(br)
                    self._beats_since_shift += 1

                # Base color shift on phrase boundary
                if self._beats_since_shift >= self._config.base_shift_beats:
                    self._beats_since_shift = 0
                    self._current_base_color = self._next_palette_color()
                    r, g, b = self._current_base_color
                    self._apply_base_color(r, g, b)

        finally:
            if proc and proc.poll() is None:
                proc.terminate()
                proc.wait()
            print("[aether] PARTY: ended", file=sys.stderr)
```

- [ ] **Step 6: Update modes __init__.py**

Replace `src/aether/modes/__init__.py`:

```python
from aether.modes.focus import FocusMode
from aether.modes.sleep import SleepMode
from aether.modes.dj import DJMode
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd /home/digitalghost/projects/aether && .venv/bin/pytest tests/test_dj.py -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
cd /home/digitalghost/projects/aether
git add pyproject.toml src/aether/modes/dj.py src/aether/modes/__init__.py tests/test_dj.py
git commit -m "feat: implement PARTY mode with PipeWire audio tap and librosa beat detection"
```

---

### Task 7: Suppress Absence Detection in FOCUS/PARTY

**Files:**
- Modify: `src/aether/vision/presence.py`
- Modify: `tests/test_presence.py`

- [ ] **Step 1: Write failing test for absence suppression**

Add to `tests/test_presence.py`:

```python
import time
from unittest.mock import MagicMock
from aether.vision.presence import PresenceTracker
from aether.state import StateMachine, State, Event


def test_absence_suppressed_in_focus():
    sm = StateMachine()
    sm.handle_event(Event.FOCUS_START)
    assert sm.state == State.FOCUS
    tracker = PresenceTracker(absence_timeout_sec=1, state_machine=sm)
    # Simulate no human for longer than timeout
    t0 = time.monotonic()
    tracker.update(False, now=t0)
    tracker.update(False, now=t0 + 2)
    # Should still be in FOCUS, not AWAY
    assert sm.state == State.FOCUS


def test_absence_suppressed_in_party():
    sm = StateMachine()
    sm.handle_event(Event.PARTY_START)
    assert sm.state == State.PARTY
    tracker = PresenceTracker(absence_timeout_sec=1, state_machine=sm)
    t0 = time.monotonic()
    tracker.update(False, now=t0)
    tracker.update(False, now=t0 + 2)
    assert sm.state == State.PARTY


def test_absence_still_works_in_present():
    sm = StateMachine()
    tracker = PresenceTracker(absence_timeout_sec=1, state_machine=sm)
    t0 = time.monotonic()
    tracker.update(True, now=t0)
    tracker.update(False, now=t0 + 0.5)
    tracker.update(False, now=t0 + 2)
    assert sm.state == State.AWAY
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/digitalghost/projects/aether && .venv/bin/pytest tests/test_presence.py::test_absence_suppressed_in_focus tests/test_presence.py::test_absence_suppressed_in_party tests/test_presence.py::test_absence_still_works_in_present -v`
Expected: `test_absence_suppressed_in_focus` and `test_absence_suppressed_in_party` FAIL (state transitions to AWAY because the tracker doesn't check current state before firing HUMAN_ABSENT)

- [ ] **Step 3: Add absence suppression to PresenceTracker**

In `src/aether/vision/presence.py`, modify the `update` method of `PresenceTracker`:

Replace:

```python
    def update(self, human_detected: bool, now: float | None = None) -> None:
        now = now if now is not None else time.monotonic()

        if human_detected:
            self._last_human_seen = now
            self._absence_fired = False

            if self._sm.state == State.AWAY:
                self._sm.handle_event(Event.HUMAN_DETECTED)
        else:
            elapsed = now - self._last_human_seen
            if elapsed >= self._timeout and not self._absence_fired:
                self._absence_fired = True
                self._sm.handle_event(Event.HUMAN_ABSENT)
```

With:

```python
    # States where absence detection is suppressed
    _ABSENCE_SUPPRESSED = {State.FOCUS, State.PARTY}

    def update(self, human_detected: bool, now: float | None = None) -> None:
        now = now if now is not None else time.monotonic()

        if human_detected:
            self._last_human_seen = now
            self._absence_fired = False

            if self._sm.state == State.AWAY:
                self._sm.handle_event(Event.HUMAN_DETECTED)
        else:
            if self._sm.state in self._ABSENCE_SUPPRESSED:
                return
            elapsed = now - self._last_human_seen
            if elapsed >= self._timeout and not self._absence_fired:
                self._absence_fired = True
                self._sm.handle_event(Event.HUMAN_ABSENT)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/digitalghost/projects/aether && .venv/bin/pytest tests/test_presence.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
cd /home/digitalghost/projects/aether
git add src/aether/vision/presence.py tests/test_presence.py
git commit -m "feat: suppress absence detection in FOCUS and PARTY states"
```

---

### Task 8: Wire CLI Commands and Daemon Integration

**Files:**
- Modify: `src/aether/cli.py`
- Modify: `src/aether/lighting/circadian.py`

This is the integration task — connecting modes to the daemon loop, adding CLI commands, and extending status.

- [ ] **Step 1: Update CircadianEngine to defer to active modes**

In `src/aether/lighting/circadian.py`, modify `on_state_change` and `run` to handle new states:

Replace the `on_state_change` method:

```python
    def on_state_change(self, new_state: State) -> None:
        self._state = new_state
        if new_state == State.AWAY:
            nightlight = self._palettes.get("nightlight", ColorState(180, 140, 60, 5))
            self._zones.set_all(nightlight)
```

With:

```python
    def on_state_change(self, new_state: State) -> None:
        self._state = new_state
        if new_state == State.AWAY:
            nightlight = self._palettes.get("nightlight", ColorState(180, 140, 60, 5))
            self._zones.set_all(nightlight)
        # FOCUS, PARTY, SLEEP handle their own lighting — circadian yields
```

Replace the `run` method's main loop body:

```python
    async def run(self) -> None:
        while True:
            if self._ramping:
                await asyncio.sleep(0.1)
                continue

            await self._ensure_sun_times()

            if self._state == State.AWAY:
                nightlight = self._palettes.get("nightlight", ColorState(180, 140, 60, 5))
                self._zones.set_all(nightlight)
            elif self._state == State.PRESENT and self._sun is not None:
                now = datetime.now()
                phase = compute_phase(now, self._sun)
                target = phase_color(phase, self._palettes)
                self._zones.set_all(target)
            # FOCUS, PARTY, SLEEP: do nothing — their coroutines control lighting

            await asyncio.sleep(self._config.circadian.update_interval_sec)
```

- [ ] **Step 2: Rewrite cli.py with mode integration**

Replace `src/aether/cli.py`:

```python
# src/aether/cli.py
from __future__ import annotations

import asyncio
import json
import sys

import click

from aether.config import load_config
from aether.state import StateMachine, State, Event, Transition
from aether.vision.camera import Camera
from aether.vision.presence import PresenceDetector
from aether.lighting.circadian import CircadianEngine
from aether.lighting.zones import ZoneManager
from aether.adapters.mqtt import MqttClient
from aether.adapters.govee import GoveeAdapter
from aether.alerts.sentry import SentryAlert
from aether.modes.focus import FocusMode
from aether.modes.sleep import SleepMode
from aether.modes.dj import DJMode


@click.group()
def cli():
    """Aether — The Living Room"""
    pass


@cli.command()
@click.option("--config", "config_path", type=click.Path(), default=None, help="Config file path")
def run(config_path):
    """Start the Aether daemon."""
    from pathlib import Path

    path = Path(config_path) if config_path else None
    config = load_config(path)

    print("[aether] Starting daemon...", file=sys.stderr)
    asyncio.run(_run_daemon(config))


async def _run_daemon(config):
    mqtt = MqttClient(broker=config.mqtt.broker, port=config.mqtt.port)
    adapter = GoveeAdapter(mqtt, config.zones, topic_prefix=config.mqtt.topic_prefix)
    zones = ZoneManager(adapter)
    state_machine = StateMachine()
    circadian = CircadianEngine(config, zones)
    presence = PresenceDetector(config.presence, state_machine)
    camera = Camera(config.presence.camera_index, config.presence.frame_interval_ms)
    sentry = SentryAlert(
        adapter=adapter,
        floor_zone_name="floor",
        flash_color=config.alerts.sentry.floor_flash_color,
        flash_count=config.alerts.sentry.floor_flash_count,
    )

    alert_task = None
    active_mode_task = None
    mode_cancel = asyncio.Event()
    mode_pause = asyncio.Event()

    def _stop_active_mode():
        nonlocal active_mode_task
        if active_mode_task and not active_mode_task.done():
            mode_cancel.set()
            active_mode_task = None

    def _start_mode(coro):
        nonlocal active_mode_task
        mode_cancel.clear()
        active_mode_task = asyncio.ensure_future(coro)

        async def _on_mode_done(task):
            try:
                await task
            except Exception as e:
                print(f"[aether] Mode error: {e}", file=sys.stderr)
            # If mode ended naturally (not cancelled), transition back
            if not mode_cancel.is_set():
                if state_machine.state == State.FOCUS:
                    state_machine.handle_event(Event.FOCUS_STOP)
                elif state_machine.state == State.PARTY:
                    state_machine.handle_event(Event.PARTY_STOP)
                elif state_machine.state == State.SLEEP:
                    # Check if sleep completed
                    state_machine.handle_event(Event.SLEEP_COMPLETE)

        asyncio.ensure_future(_on_mode_done(active_mode_task))

    def handle_transition(t: Transition):
        nonlocal alert_task
        print(f"[aether] {t.from_state.value} → {t.to_state.value} ({t.reason})", file=sys.stderr)
        adapter.publish_state(t.to_state.value)
        adapter.publish_transition(t.from_state.value, t.to_state.value, t.reason)
        circadian.on_state_change(t.to_state)

        if t.to_state == State.PRESENT and t.from_state == State.AWAY:
            asyncio.ensure_future(circadian.run_return_ramp())

        if t.to_state == State.PRESENT and t.from_state in (State.FOCUS, State.PARTY, State.SLEEP):
            _stop_active_mode()
            # Restore circadian lighting
            asyncio.ensure_future(circadian.run_return_ramp())

        if t.to_state == State.FOCUS:
            focus = FocusMode(config.focus, zones, mode_cancel, mode_pause)
            _start_mode(focus.run())

        elif t.to_state == State.PARTY:
            party = DJMode(config.party, zones, mqtt, mode_cancel, mode_pause)
            _start_mode(party.run())

        elif t.to_state == State.SLEEP:
            sleep = SleepMode(config.sleep, zones, mqtt, mode_cancel, mode_pause)
            _start_mode(sleep.run())

        elif t.to_state == State.AWAY and t.from_state == State.SLEEP:
            _stop_active_mode()

    state_machine._on_transition = handle_transition

    # MQTT command handler
    def _handle_mqtt_command(topic: str, payload: str):
        payload = payload.strip().strip('"')
        if topic == f"{config.mqtt.topic_prefix}/mode/set":
            if payload == "focus" and state_machine.state == State.PRESENT:
                state_machine.handle_event(Event.FOCUS_START)
            elif payload == "party" and state_machine.state == State.PRESENT:
                state_machine.handle_event(Event.PARTY_START)
            elif payload == "sleep" and state_machine.state == State.PRESENT:
                state_machine.handle_event(Event.SLEEP_START)
            elif payload == "focus_stop" and state_machine.state == State.FOCUS:
                state_machine.handle_event(Event.FOCUS_STOP)
            elif payload == "party_stop" and state_machine.state == State.PARTY:
                state_machine.handle_event(Event.PARTY_STOP)
            elif payload == "sleep_stop" and state_machine.state == State.SLEEP:
                state_machine.handle_event(Event.SLEEP_CANCEL)
        elif topic == f"{config.mqtt.topic_prefix}/control":
            if payload == "pause":
                zones.paused = True
                mode_pause.set()
                mqtt.publish(f"{config.mqtt.topic_prefix}/paused", json.dumps(True), retain=True)
                print("[aether] Paused", file=sys.stderr)
            elif payload == "resume":
                zones.paused = False
                mode_pause.clear()
                zones.flush_current()
                mqtt.publish(f"{config.mqtt.topic_prefix}/paused", json.dumps(False), retain=True)
                print("[aether] Resumed", file=sys.stderr)

    mqtt.on_message = _handle_mqtt_command
    mqtt.subscribe(f"{config.mqtt.topic_prefix}/mode/set")
    mqtt.subscribe(f"{config.mqtt.topic_prefix}/control")

    # Wrap presence to also publish MQTT + trigger sentry
    original_update = presence.tracker.update

    def update_with_mqtt(human_detected: bool, now: float | None = None):
        nonlocal alert_task
        adapter.publish_presence(human_detected)

        if human_detected and state_machine.state == State.AWAY:
            if alert_task is None or alert_task.done():
                alert_task = asyncio.ensure_future(sentry.trigger())

        original_update(human_detected, now)

    presence.tracker.update = update_with_mqtt

    print("[aether] Daemon running. Press Ctrl+C to stop.", file=sys.stderr)

    try:
        await asyncio.gather(
            camera.run(presence.process_frame),
            circadian.run(),
            mqtt.run(),
        )
    except KeyboardInterrupt:
        print("\n[aether] Shutting down...", file=sys.stderr)
    finally:
        _stop_active_mode()
        camera.release()
        mqtt.disconnect()


def _publish_command(broker: str, port: int, topic: str, payload: str):
    """One-shot MQTT publish for CLI commands."""
    import paho.mqtt.client as paho_mqtt

    client = paho_mqtt.Client(paho_mqtt.CallbackAPIVersion.VERSION2)
    client.connect(broker, port)
    client.publish(topic, payload, qos=1)
    client.disconnect()


@cli.command()
@click.option("--cycles", default=None, type=int, help="Number of Pomodoro cycles (0=indefinite)")
@click.option("--work", default=None, type=int, help="Work period in minutes")
@click.option("--break", "break_min", default=None, type=int, help="Short break in minutes")
@click.option("--config", "config_path", type=click.Path(), default=None)
def focus(cycles, work, break_min, config_path):
    """Enter FOCUS mode (Pomodoro)."""
    from pathlib import Path
    config = load_config(Path(config_path) if config_path else None)
    _publish_command(config.mqtt.broker, config.mqtt.port,
                     f"{config.mqtt.topic_prefix}/mode/set", "focus")
    click.echo("FOCUS mode activated.")


@cli.group(invoke_without_command=True)
@click.pass_context
def focus_group(ctx):
    """FOCUS mode commands."""
    pass


@cli.command("focus-stop")
@click.option("--config", "config_path", type=click.Path(), default=None)
def focus_stop(config_path):
    """Exit FOCUS mode."""
    from pathlib import Path
    config = load_config(Path(config_path) if config_path else None)
    _publish_command(config.mqtt.broker, config.mqtt.port,
                     f"{config.mqtt.topic_prefix}/mode/set", "focus_stop")
    click.echo("FOCUS mode stopped.")


@cli.command()
@click.option("--config", "config_path", type=click.Path(), default=None)
def party(config_path):
    """Enter PARTY mode (DJ Lightshow)."""
    from pathlib import Path
    config = load_config(Path(config_path) if config_path else None)
    _publish_command(config.mqtt.broker, config.mqtt.port,
                     f"{config.mqtt.topic_prefix}/mode/set", "party")
    click.echo("PARTY mode activated.")


@cli.command("party-stop")
@click.option("--config", "config_path", type=click.Path(), default=None)
def party_stop(config_path):
    """Exit PARTY mode."""
    from pathlib import Path
    config = load_config(Path(config_path) if config_path else None)
    _publish_command(config.mqtt.broker, config.mqtt.port,
                     f"{config.mqtt.topic_prefix}/mode/set", "party_stop")
    click.echo("PARTY mode stopped.")


@cli.command()
@click.option("--config", "config_path", type=click.Path(), default=None)
def sleep(config_path):
    """Enter SLEEP mode (cascade shutdown)."""
    from pathlib import Path
    config = load_config(Path(config_path) if config_path else None)
    _publish_command(config.mqtt.broker, config.mqtt.port,
                     f"{config.mqtt.topic_prefix}/mode/set", "sleep")
    click.echo("SLEEP mode activated.")


@cli.command("sleep-stop")
@click.option("--config", "config_path", type=click.Path(), default=None)
def sleep_stop(config_path):
    """Cancel SLEEP mode."""
    from pathlib import Path
    config = load_config(Path(config_path) if config_path else None)
    _publish_command(config.mqtt.broker, config.mqtt.port,
                     f"{config.mqtt.topic_prefix}/mode/set", "sleep_stop")
    click.echo("SLEEP mode cancelled.")


@cli.command()
@click.option("--config", "config_path", type=click.Path(), default=None)
def pause(config_path):
    """Pause all light output."""
    from pathlib import Path
    config = load_config(Path(config_path) if config_path else None)
    _publish_command(config.mqtt.broker, config.mqtt.port,
                     f"{config.mqtt.topic_prefix}/control", "pause")
    click.echo("Aether paused.")


@cli.command()
@click.option("--config", "config_path", type=click.Path(), default=None)
def resume(config_path):
    """Resume light output."""
    from pathlib import Path
    config = load_config(Path(config_path) if config_path else None)
    _publish_command(config.mqtt.broker, config.mqtt.port,
                     f"{config.mqtt.topic_prefix}/control", "resume")
    click.echo("Aether resumed.")


@cli.command()
def status():
    """Show current Aether state."""
    import paho.mqtt.client as paho_mqtt

    results = {}
    topics = [
        "aether/state",
        "aether/presence/human",
        "aether/presence/last_seen",
        "aether/paused",
        "aether/focus/state",
        "aether/focus/timer",
        "aether/sleep/stage",
    ]

    def on_connect(client, userdata, flags, rc, properties=None):
        for t in topics:
            client.subscribe(t)

    def on_message(client, userdata, msg):
        results[msg.topic] = msg.payload.decode()
        if len(results) >= len(topics):
            client.disconnect()

    client = paho_mqtt.Client(paho_mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect("localhost", 1883)
        client.loop_start()

        import time
        deadline = time.time() + 3
        while len(results) < len(topics) and time.time() < deadline:
            time.sleep(0.1)

        client.loop_stop()
        client.disconnect()
    except Exception as e:
        click.echo(f"Cannot connect to MQTT broker: {e}", err=True)
        sys.exit(1)

    click.echo(f"State:     {results.get('aether/state', 'unknown')}")
    click.echo(f"Human:     {results.get('aether/presence/human', 'unknown')}")
    click.echo(f"Last seen: {results.get('aether/presence/last_seen', 'unknown')}")
    click.echo(f"Paused:    {results.get('aether/paused', 'false')}")

    focus_state = results.get("aether/focus/state")
    if focus_state:
        click.echo(f"Focus:     {focus_state}")
    focus_timer = results.get("aether/focus/timer")
    if focus_timer:
        try:
            timer = json.loads(focus_timer)
            click.echo(f"  Timer:   {timer['remaining_sec']}s remaining (cycle {timer['cycle']}/{timer['total_cycles']})")
        except Exception:
            pass

    sleep_stage = results.get("aether/sleep/stage")
    if sleep_stage:
        click.echo(f"Sleep:     {sleep_stage}")


@cli.command()
@click.option("--config", "config_path", type=click.Path(), default=None, help="Config file path")
def discover(config_path):
    """Discover Govee devices and map them to zones."""
    import json
    from pathlib import Path
    import httpx
    import yaml

    path = Path(config_path) if config_path else None
    config = load_config(path)
    config_file_path = path or (Path.home() / ".config" / "aether" / "config.yaml")

    click.echo("Querying govee2mqtt HTTP API for devices...")

    try:
        resp = httpx.get("http://localhost:8056/api/devices", timeout=5)
        resp.raise_for_status()
        all_devices = resp.json()
    except Exception as e:
        click.echo(f"Cannot connect to govee2mqtt API: {e}", err=True)
        click.echo("Is govee2mqtt running? (docker ps | grep govee2mqtt)", err=True)
        sys.exit(1)

    devices = [
        d for d in all_devices
        if d.get("sku", "").startswith("H") and d.get("name")
    ]

    if not devices:
        click.echo("No Govee light devices found.")
        sys.exit(1)

    click.echo(f"\nFound {len(devices)} Govee devices:")
    for i, dev in enumerate(devices, 1):
        state = dev.get("state", {})
        online = "online" if state and state.get("online") else "offline"
        on_off = "ON" if state and state.get("on") else "OFF"
        click.echo(f"  {i}. {dev['name']} ({dev['sku']}) [{online}, {on_off}]")

    def mqtt_device_id(raw_id: str) -> str:
        return raw_id.replace(":", "")

    zone_names = ["wall_left", "wall_right", "monitor", "floor", "bedroom"]
    zone_map = {}

    click.echo("\nMap devices to zones (enter number, or 0 to skip):")
    for zone in zone_names:
        while True:
            choice = click.prompt(f"  {zone}", type=int, default=0)
            if choice == 0:
                break
            if 1 <= choice <= len(devices):
                zone_map[zone] = mqtt_device_id(devices[choice - 1]["id"])
                break
            click.echo(f"  Invalid choice. Enter 1-{len(devices)} or 0 to skip.")

    with open(config_file_path) as f:
        raw = yaml.safe_load(f) or {}

    if "zones" not in raw:
        raw["zones"] = {}
    for zone, dev_id in zone_map.items():
        if zone not in raw["zones"]:
            raw["zones"][zone] = {}
        raw["zones"][zone]["govee_device"] = dev_id

    with open(config_file_path, "w") as f:
        yaml.dump(raw, f, default_flow_style=False)

    click.echo(f"\nConfig updated at {config_file_path}")
    click.echo("Mapped zones:")
    for zone, dev_id in zone_map.items():
        click.echo(f"  {zone} → {dev_id}")
```

- [ ] **Step 3: Add subscribe and on_message support to MqttClient**

In `src/aether/adapters/mqtt.py`, add subscribe capability. Add after `_flush_buffer`:

```python
    def __init__(self, broker: str = "localhost", port: int = 1883):
        self._broker = broker
        self._port = port
        self._client = paho_mqtt.Client(paho_mqtt.CallbackAPIVersion.VERSION2)
        self._connected = False
        self._buffer: list[tuple[str, str, bool]] = []
        self._max_buffer = 10
        self._subscriptions: list[str] = []
        self.on_message: Callable[[str, str], None] | None = None
```

Add the `subscribe` method and update `_on_connect`:

```python
    def subscribe(self, topic: str) -> None:
        self._subscriptions.append(topic)
        if self._connected:
            self._client.subscribe(topic, qos=1)

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            self._connected = True
            print(f"[aether] MQTT connected to {self._broker}:{self._port}", file=sys.stderr)
            self._flush_buffer()
            for topic in self._subscriptions:
                self._client.subscribe(topic, qos=1)
        else:
            print(f"[aether] MQTT connection failed: rc={rc}", file=sys.stderr)
```

Add message handler in `run`, before the `while True` loop:

```python
    async def run(self) -> None:
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect

        def _on_msg(client, userdata, msg):
            if self.on_message:
                try:
                    self.on_message(msg.topic, msg.payload.decode())
                except Exception as e:
                    print(f"[aether] MQTT message handler error: {e}", file=sys.stderr)

        self._client.on_message = _on_msg

        while True:
            try:
                self._client.connect(self._broker, self._port)
                self._client.loop_start()
                while True:
                    await asyncio.sleep(1)
            except Exception as e:
                print(f"[aether] MQTT error: {e}. Retrying in 5s...", file=sys.stderr)
                self._connected = False
                await asyncio.sleep(5)
```

Add the `Callable` import at the top of `mqtt.py`:

```python
from typing import Any, Callable
```

- [ ] **Step 4: Run all tests**

Run: `cd /home/digitalghost/projects/aether && .venv/bin/pytest -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
cd /home/digitalghost/projects/aether
git add src/aether/cli.py src/aether/adapters/mqtt.py src/aether/lighting/circadian.py
git commit -m "feat: wire Phase 2 modes into daemon with CLI commands and MQTT control"
```

---

### Task 9: Update CLAUDE.md and Run Full Test Suite

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update CLAUDE.md with Phase 2 commands**

Add to the Commands section in `CLAUDE.md`:

```markdown
# Phase 2 modes
python -m aether focus             # Start Pomodoro focus session
python -m aether focus-stop        # Exit focus mode
python -m aether party             # Start DJ lightshow
python -m aether party-stop        # Stop party mode
python -m aether sleep             # Start cascade shutdown
python -m aether sleep-stop        # Cancel sleep cascade
python -m aether pause             # Pause all light output
python -m aether resume            # Resume light output
```

- [ ] **Step 2: Run full test suite**

Run: `cd /home/digitalghost/projects/aether && .venv/bin/pytest -v`
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
cd /home/digitalghost/projects/aether
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with Phase 2 commands"
```

---

## Task Dependency Order

```
Task 1 (state machine) ─┬─► Task 4 (FOCUS)  ─┐
                         ├─► Task 5 (SLEEP)  ─┼─► Task 8 (CLI wiring) ─► Task 9 (docs + full test)
Task 2 (config)     ─────┤─► Task 6 (PARTY)  ─┘
                         │
Task 3 (pause)      ─────┘
                         │
Task 7 (absence)    ─────┘
```

Tasks 1, 2, 3 can run in parallel. Tasks 4, 5, 6, 7 can run in parallel after 1+2+3. Task 8 depends on all prior tasks. Task 9 is final.
