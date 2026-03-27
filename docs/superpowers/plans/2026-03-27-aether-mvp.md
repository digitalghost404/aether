# Aether MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a presence-aware circadian lighting daemon that controls 5 Govee devices via MQTT, transitioning between PRESENT and AWAY states based on human detection from a webcam.

**Architecture:** Single Python async process. C920 webcam → MediaPipe pose detection (3fps, CPU-only) → state machine (PRESENT/AWAY with 10s timer) → circadian lighting engine → MQTT → govee2mqtt → Govee devices. Config via Pydantic + YAML.

**Tech Stack:** Python 3.11+, MediaPipe, OpenCV (headless), paho-mqtt, Pydantic, httpx, Click, asyncio

**Spec:** `docs/superpowers/specs/2026-03-27-aether-design.md`

---

## File Map

| File | Responsibility | Created In |
|------|---------------|------------|
| `pyproject.toml` | Project metadata, deps, entry points | Task 1 |
| `config.example.yaml` | Default config template | Task 2 |
| `src/aether/__init__.py` | Package init, version | Task 1 |
| `src/aether/__main__.py` | `python -m aether` entry point | Task 9 |
| `src/aether/cli.py` | Click CLI: run, discover, status | Task 9, 10, 11 |
| `src/aether/config.py` | Pydantic config model + YAML loader | Task 2 |
| `src/aether/state.py` | State machine (enum + transition table) | Task 3 |
| `src/aether/vision/__init__.py` | Package init | Task 4 |
| `src/aether/vision/camera.py` | C920 async capture loop | Task 4 |
| `src/aether/vision/presence.py` | MediaPipe pose → human detection + timer | Task 5 |
| `src/aether/lighting/__init__.py` | Package init | Task 6 |
| `src/aether/lighting/ramp.py` | Color/brightness interpolation | Task 6 |
| `src/aether/lighting/zones.py` | Zone registry + color targets | Task 6 |
| `src/aether/lighting/circadian.py` | Sunrise API + palette engine + tick loop | Task 7 |
| `src/aether/adapters/__init__.py` | Package init | Task 8 |
| `src/aether/adapters/mqtt.py` | paho-mqtt wrapper | Task 8 |
| `src/aether/adapters/govee.py` | GoveeAdapter: zone → govee2mqtt topics | Task 8 |
| `src/aether/alerts/__init__.py` | Package init | Task 5 |
| `src/aether/alerts/sentry.py` | AWAY human detection alert + flash | Task 5 |
| `tests/test_state.py` | State machine unit tests | Task 3 |
| `tests/test_config.py` | Config loading/validation tests | Task 2 |
| `tests/test_ramp.py` | Color interpolation tests | Task 6 |
| `tests/test_circadian.py` | Phase computation + timing tests | Task 7 |
| `tests/test_presence.py` | Presence timer logic tests | Task 5 |
| `tests/test_govee_adapter.py` | MQTT topic translation tests | Task 8 |
| `tests/conftest.py` | Shared fixtures | Task 2 |
| `systemd/aether.service` | Systemd user unit | Task 11 |
| `CLAUDE.md` | Project context | Task 11 |

---

### Task 1: Project Scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `src/aether/__init__.py`
- Create: `.gitignore`

- [ ] **Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "aether"
version = "0.1.0"
description = "Room-scale presence-aware circadian lighting daemon"
requires-python = ">=3.11"
dependencies = [
    "mediapipe>=0.10",
    "opencv-python-headless",
    "paho-mqtt>=2.0",
    "pydantic>=2.0",
    "pyyaml>=6.0",
    "httpx",
    "click",
]

[project.optional-dependencies]
dev = [
    "pytest",
    "pytest-asyncio",
]

[project.scripts]
aether = "aether.cli:cli"
```

- [ ] **Step 2: Create package init**

```python
# src/aether/__init__.py
__version__ = "0.1.0"
```

- [ ] **Step 3: Create .gitignore**

```
__pycache__/
*.pyc
*.egg-info/
dist/
.venv/
.pytest_cache/
```

- [ ] **Step 4: Create virtual environment and install**

Run: `cd ~/projects/aether && python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"`

Expected: Install completes. MediaPipe and OpenCV download (~400MB).

- [ ] **Step 5: Verify install**

Run: `cd ~/projects/aether && source .venv/bin/activate && python -c "import aether; print(aether.__version__)"`

Expected: `0.1.0`

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/aether/__init__.py .gitignore
git commit -m "feat: project scaffold with dependencies"
```

---

### Task 2: Config Model

**Files:**
- Create: `src/aether/config.py`
- Create: `config.example.yaml`
- Create: `tests/conftest.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing config tests**

```python
# tests/test_config.py
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
```

- [ ] **Step 2: Create conftest.py**

```python
# tests/conftest.py
import pytest
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd ~/projects/aether && source .venv/bin/activate && pytest tests/test_config.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'aether.config'`

- [ ] **Step 4: Write config.example.yaml**

```yaml
# Aether Configuration
# Copy to ~/.config/aether/config.yaml and edit

location:
  latitude: null        # Required — your latitude for sunrise/sunset
  longitude: null       # Required — your longitude for sunrise/sunset

presence:
  camera_index: 0                # /dev/video index
  absence_timeout_sec: 10        # Seconds with no human before AWAY
  detection_confidence: 0.5      # MediaPipe min detection confidence (0.0-1.0)
  frame_interval_ms: 333         # ~3fps — increase for lower CPU usage

mqtt:
  broker: localhost
  port: 1883
  topic_prefix: aether

circadian:
  update_interval_sec: 1         # Steady-state tick rate (seconds)
  ramp_interval_ms: 100          # Tick rate during ramps (10/sec)
  return_ramp_sec: 8             # Compressed sunrise duration on return
  sunrise_offset_min: 0          # Shift sunrise ± minutes
  sunset_offset_min: 0           # Shift sunset ± minutes
  palettes:
    dawn:
      color: [255, 160, 50]
      brightness: 30
    morning:
      color: [255, 240, 220]
      brightness: 80
    midday:
      color: [255, 255, 255]
      brightness: 100
    golden_hour:
      color: [255, 180, 60]
      brightness: 70
    evening:
      color: [80, 60, 180]
      brightness: 40
    night:
      color: [30, 20, 80]
      brightness: 15
    nightlight:
      color: [180, 140, 60]
      brightness: 5

zones:
  wall_left:
    govee_device: null
  wall_right:
    govee_device: null
  monitor:
    govee_device: null
  floor:
    govee_device: null
  bedroom:
    govee_device: null

alerts:
  sentry:
    floor_flash_color: [255, 180, 0]
    floor_flash_count: 3
```

- [ ] **Step 5: Write config.py**

```python
# src/aether/config.py
from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Annotated

import yaml
from pydantic import BaseModel, Field, field_validator

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "aether" / "config.yaml"
EXAMPLE_CONFIG_PATH = Path(__file__).parent.parent.parent / "config.example.yaml"


class LocationConfig(BaseModel):
    latitude: float | None = None
    longitude: float | None = None


class PresenceConfig(BaseModel):
    camera_index: int = 0
    absence_timeout_sec: int = 10
    detection_confidence: float = 0.5
    frame_interval_ms: int = 333


class MqttConfig(BaseModel):
    broker: str = "localhost"
    port: int = 1883
    topic_prefix: str = "aether"


class PaletteEntry(BaseModel):
    color: list[int] = Field(..., min_length=3, max_length=3)
    brightness: Annotated[int, Field(ge=0, le=100)]

    @field_validator("color")
    @classmethod
    def validate_color(cls, v: list[int]) -> list[int]:
        for c in v:
            if not 0 <= c <= 255:
                raise ValueError(f"Color value {c} must be 0-255")
        return v


class CircadianConfig(BaseModel):
    update_interval_sec: int = 1
    ramp_interval_ms: int = 100
    return_ramp_sec: int = 8
    sunrise_offset_min: int = 0
    sunset_offset_min: int = 0
    palettes: dict[str, PaletteEntry] = {}


class ZoneConfig(BaseModel):
    govee_device: str | None = None


class SentryAlertConfig(BaseModel):
    floor_flash_color: list[int] = [255, 180, 0]
    floor_flash_count: int = 3


class AlertsConfig(BaseModel):
    sentry: SentryAlertConfig = SentryAlertConfig()


class AetherConfig(BaseModel):
    location: LocationConfig = LocationConfig()
    presence: PresenceConfig = PresenceConfig()
    mqtt: MqttConfig = MqttConfig()
    circadian: CircadianConfig = CircadianConfig()
    zones: dict[str, ZoneConfig] = {}
    alerts: AlertsConfig = AlertsConfig()


def load_config(path: Path | None = None) -> AetherConfig:
    path = path or DEFAULT_CONFIG_PATH

    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        if EXAMPLE_CONFIG_PATH.exists():
            shutil.copy(EXAMPLE_CONFIG_PATH, path)
        print(
            f"[aether] Config not found. Created default at {path}\n"
            f"[aether] Please set location.latitude and location.longitude, then re-run.",
            file=sys.stderr,
        )
        sys.exit(1)

    with open(path) as f:
        raw = yaml.safe_load(f) or {}

    return AetherConfig(**raw)
```

- [ ] **Step 6: Run tests**

Run: `cd ~/projects/aether && source .venv/bin/activate && pytest tests/test_config.py -v`

Expected: All 5 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add src/aether/config.py config.example.yaml tests/conftest.py tests/test_config.py
git commit -m "feat: config model with Pydantic validation and YAML loading"
```

---

### Task 3: State Machine

**Files:**
- Create: `src/aether/state.py`
- Create: `tests/test_state.py`

- [ ] **Step 1: Write failing state machine tests**

```python
# tests/test_state.py
import pytest
from aether.state import State, Event, StateMachine, InvalidTransition


def test_initial_state_is_present():
    sm = StateMachine()
    assert sm.state == State.PRESENT


def test_present_to_away():
    transitions = []
    sm = StateMachine(on_transition=lambda t: transitions.append(t))
    sm.handle_event(Event.HUMAN_ABSENT)
    assert sm.state == State.AWAY
    assert len(transitions) == 1
    assert transitions[0].from_state == State.PRESENT
    assert transitions[0].to_state == State.AWAY


def test_away_to_present():
    sm = StateMachine()
    sm.handle_event(Event.HUMAN_ABSENT)
    assert sm.state == State.AWAY

    transitions = []
    sm = StateMachine(on_transition=lambda t: transitions.append(t))
    sm.handle_event(Event.HUMAN_ABSENT)
    sm.handle_event(Event.HUMAN_DETECTED)
    assert sm.state == State.PRESENT
    assert len(transitions) == 2


def test_duplicate_present_ignored():
    transitions = []
    sm = StateMachine(on_transition=lambda t: transitions.append(t))
    sm.handle_event(Event.HUMAN_DETECTED)
    assert sm.state == State.PRESENT
    assert len(transitions) == 0


def test_duplicate_away_ignored():
    transitions = []
    sm = StateMachine(on_transition=lambda t: transitions.append(t))
    sm.handle_event(Event.HUMAN_ABSENT)
    sm.handle_event(Event.HUMAN_ABSENT)
    assert sm.state == State.AWAY
    assert len(transitions) == 1


def test_transition_has_reason():
    transitions = []
    sm = StateMachine(on_transition=lambda t: transitions.append(t))
    sm.handle_event(Event.HUMAN_ABSENT)
    assert transitions[0].reason == "human_absent"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/projects/aether && source .venv/bin/activate && pytest tests/test_state.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'aether.state'`

- [ ] **Step 3: Write state machine implementation**

```python
# src/aether/state.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Callable


class State(Enum):
    PRESENT = "present"
    AWAY = "away"
    # Phase 2:
    # FOCUS = "focus"
    # PARTY = "party"
    # SLEEP = "sleep"


class Event(Enum):
    HUMAN_DETECTED = "human_detected"
    HUMAN_ABSENT = "human_absent"
    # Phase 2:
    # FOCUS_START = "focus_start"
    # FOCUS_STOP = "focus_stop"
    # PARTY_START = "party_start"
    # PARTY_STOP = "party_stop"
    # SLEEP_START = "sleep_start"
    # WAKE = "wake"


@dataclass(frozen=True)
class Transition:
    from_state: State
    to_state: State
    reason: str
    timestamp: datetime


# Valid transitions: (current_state, event) → new_state
TRANSITION_TABLE: dict[tuple[State, Event], State] = {
    (State.PRESENT, Event.HUMAN_ABSENT): State.AWAY,
    (State.AWAY, Event.HUMAN_DETECTED): State.PRESENT,
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
            return None  # No valid transition — ignore

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

- [ ] **Step 4: Run tests**

Run: `cd ~/projects/aether && source .venv/bin/activate && pytest tests/test_state.py -v`

Expected: All 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aether/state.py tests/test_state.py
git commit -m "feat: state machine with PRESENT/AWAY transitions"
```

---

### Task 4: Camera Capture

**Files:**
- Create: `src/aether/vision/__init__.py`
- Create: `src/aether/vision/camera.py`

- [ ] **Step 1: Create vision package init**

```python
# src/aether/vision/__init__.py
```

- [ ] **Step 2: Write camera module**

```python
# src/aether/vision/camera.py
from __future__ import annotations

import asyncio
import sys
import time
from typing import Callable

import cv2
import numpy as np


class Camera:
    def __init__(self, camera_index: int = 0, frame_interval_ms: int = 333):
        self._camera_index = camera_index
        self._frame_interval = frame_interval_ms / 1000.0
        self._cap: cv2.VideoCapture | None = None

    def _open(self) -> bool:
        if self._cap is not None and self._cap.isOpened():
            return True
        self._cap = cv2.VideoCapture(self._camera_index)
        if not self._cap.isOpened():
            self._cap = None
            return False
        # Lower resolution for less CPU — we only need pose detection
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        return True

    def _read_frame(self) -> np.ndarray | None:
        if self._cap is None:
            return None
        ret, frame = self._cap.read()
        if not ret:
            return None
        return frame

    async def run(self, process_frame: Callable[[np.ndarray], None]) -> None:
        retry_delay = 5.0

        while True:
            if not self._open():
                print(
                    f"[aether] Camera {self._camera_index} not available. Retrying in {retry_delay}s...",
                    file=sys.stderr,
                )
                await asyncio.sleep(retry_delay)
                continue

            frame = await asyncio.to_thread(self._read_frame)

            if frame is None:
                print("[aether] Camera read failed. Reconnecting...", file=sys.stderr)
                self._cap = None
                await asyncio.sleep(retry_delay)
                continue

            process_frame(frame)
            await asyncio.sleep(self._frame_interval)

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
```

- [ ] **Step 3: Verify import works**

Run: `cd ~/projects/aether && source .venv/bin/activate && python -c "from aether.vision.camera import Camera; print('OK')"`

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add src/aether/vision/__init__.py src/aether/vision/camera.py
git commit -m "feat: async camera capture with retry and backoff"
```

---

### Task 5: Presence Detection + Sentry Alerts

**Files:**
- Create: `src/aether/vision/presence.py`
- Create: `src/aether/alerts/__init__.py`
- Create: `src/aether/alerts/sentry.py`
- Create: `tests/test_presence.py`

- [ ] **Step 1: Write failing presence tests**

```python
# tests/test_presence.py
import time
import pytest
from unittest.mock import MagicMock
from aether.vision.presence import PresenceTracker
from aether.state import State, Event


def test_human_detected_emits_event():
    sm = MagicMock()
    sm.state = State.PRESENT
    tracker = PresenceTracker(absence_timeout_sec=10, state_machine=sm)

    tracker.update(human_detected=True, now=100.0)
    # No event — already PRESENT and human detected is steady state
    sm.handle_event.assert_not_called()


def test_absence_timeout_triggers_away():
    sm = MagicMock()
    sm.state = State.PRESENT
    tracker = PresenceTracker(absence_timeout_sec=10, state_machine=sm)

    tracker.update(human_detected=True, now=100.0)
    tracker.update(human_detected=False, now=105.0)  # 5s — not yet
    sm.handle_event.assert_not_called()

    tracker.update(human_detected=False, now=111.0)  # 11s since last seen
    sm.handle_event.assert_called_once_with(Event.HUMAN_ABSENT)


def test_human_returns_triggers_present():
    sm = MagicMock()
    sm.state = State.AWAY
    tracker = PresenceTracker(absence_timeout_sec=10, state_machine=sm)
    tracker._last_human_seen = 0.0  # Long gone
    tracker._absence_fired = True

    tracker.update(human_detected=True, now=200.0)
    sm.handle_event.assert_called_once_with(Event.HUMAN_DETECTED)


def test_brief_absence_does_not_trigger():
    sm = MagicMock()
    sm.state = State.PRESENT
    tracker = PresenceTracker(absence_timeout_sec=10, state_machine=sm)

    tracker.update(human_detected=True, now=100.0)
    tracker.update(human_detected=False, now=103.0)  # 3s gap
    tracker.update(human_detected=True, now=106.0)   # Back before timeout
    sm.handle_event.assert_not_called()


def test_absence_only_fires_once():
    sm = MagicMock()
    sm.state = State.PRESENT
    tracker = PresenceTracker(absence_timeout_sec=10, state_machine=sm)

    tracker.update(human_detected=True, now=100.0)
    tracker.update(human_detected=False, now=111.0)  # Fires AWAY
    tracker.update(human_detected=False, now=120.0)  # Should NOT fire again
    assert sm.handle_event.call_count == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/projects/aether && source .venv/bin/activate && pytest tests/test_presence.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'aether.vision.presence'`

- [ ] **Step 3: Write presence tracker**

```python
# src/aether/vision/presence.py
from __future__ import annotations

import sys
import time

import mediapipe as mp
import numpy as np

from aether.state import Event, State, StateMachine


class PresenceTracker:
    """Tracks human presence and emits state machine events."""

    def __init__(self, absence_timeout_sec: int, state_machine: StateMachine):
        self._timeout = absence_timeout_sec
        self._sm = state_machine
        self._last_human_seen: float = time.monotonic()
        self._absence_fired: bool = False

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


class PresenceDetector:
    """Runs MediaPipe pose on frames and feeds PresenceTracker."""

    def __init__(self, presence_config, state_machine: StateMachine):
        self._tracker = PresenceTracker(
            absence_timeout_sec=presence_config.absence_timeout_sec,
            state_machine=state_machine,
        )
        self._pose = mp.solutions.pose.Pose(
            static_image_mode=False,
            model_complexity=0,
            min_detection_confidence=presence_config.detection_confidence,
        )

    def process_frame(self, frame: np.ndarray) -> None:
        rgb = frame[:, :, ::-1]  # BGR → RGB
        result = self._pose.process(rgb)
        human_detected = result.pose_landmarks is not None
        self._tracker.update(human_detected)

    @property
    def tracker(self) -> PresenceTracker:
        return self._tracker
```

- [ ] **Step 4: Run presence tests**

Run: `cd ~/projects/aether && source .venv/bin/activate && pytest tests/test_presence.py -v`

Expected: All 5 tests PASS.

- [ ] **Step 5: Create alerts package and sentry module**

```python
# src/aether/alerts/__init__.py
```

```python
# src/aether/alerts/sentry.py
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone


class SentryAlert:
    """Fires alerts when humans are detected in AWAY state."""

    def __init__(self, adapter, floor_zone_name: str, flash_color: list[int], flash_count: int):
        self._adapter = adapter
        self._floor_zone = floor_zone_name
        self._flash_color = flash_color
        self._flash_count = flash_count
        self._cooldown_sec = 30.0
        self._last_alert: float = 0.0

    async def trigger(self) -> None:
        import time
        now = time.monotonic()
        if now - self._last_alert < self._cooldown_sec:
            return
        self._last_alert = now

        timestamp = datetime.now(timezone.utc).isoformat()
        print(f"[aether] ALERT: Human detected while AWAY at {timestamp}", file=sys.stderr)

        self._adapter._mqtt.publish(
            "aether/alert/sentry",
            {"type": "human_detected", "timestamp": timestamp},
        )

        for _ in range(self._flash_count):
            self._adapter.publish_zone(
                self._floor_zone,
                {"r": self._flash_color[0], "g": self._flash_color[1], "b": self._flash_color[2], "brightness": 100},
            )
            await asyncio.sleep(0.5)
            self._adapter.publish_zone(
                self._floor_zone,
                {"r": 0, "g": 0, "b": 0, "brightness": 0},
            )
            await asyncio.sleep(0.5)
```

- [ ] **Step 6: Commit**

```bash
git add src/aether/vision/presence.py src/aether/alerts/__init__.py src/aether/alerts/sentry.py tests/test_presence.py
git commit -m "feat: presence detection with MediaPipe pose and sentry alerts"
```

---

### Task 6: Lighting — Ramp + Zones

**Files:**
- Create: `src/aether/lighting/__init__.py`
- Create: `src/aether/lighting/ramp.py`
- Create: `src/aether/lighting/zones.py`
- Create: `tests/test_ramp.py`

- [ ] **Step 1: Write failing ramp tests**

```python
# tests/test_ramp.py
from aether.lighting.ramp import ColorState, interpolate, generate_ramp


def test_interpolate_midpoint():
    start = ColorState(r=0, g=0, b=0, brightness=0)
    end = ColorState(r=100, g=200, b=50, brightness=100)
    mid = interpolate(start, end, 0.5)
    assert mid.r == 50
    assert mid.g == 100
    assert mid.b == 25
    assert mid.brightness == 50


def test_interpolate_start():
    start = ColorState(r=255, g=0, b=0, brightness=80)
    end = ColorState(r=0, g=255, b=0, brightness=20)
    result = interpolate(start, end, 0.0)
    assert result == start


def test_interpolate_end():
    start = ColorState(r=255, g=0, b=0, brightness=80)
    end = ColorState(r=0, g=255, b=0, brightness=20)
    result = interpolate(start, end, 1.0)
    assert result == end


def test_generate_ramp_step_count():
    start = ColorState(r=0, g=0, b=0, brightness=0)
    end = ColorState(r=255, g=255, b=255, brightness=100)
    steps = list(generate_ramp(start, end, duration_sec=8, interval_ms=100))
    assert len(steps) == 80  # 8s / 0.1s = 80 steps


def test_generate_ramp_first_and_last():
    start = ColorState(r=0, g=0, b=0, brightness=0)
    end = ColorState(r=200, g=200, b=200, brightness=100)
    steps = list(generate_ramp(start, end, duration_sec=2, interval_ms=100))
    assert steps[0].brightness < 10  # Near start
    assert steps[-1].brightness >= 95  # Near end


def test_color_state_to_dict():
    cs = ColorState(r=255, g=180, b=60, brightness=80)
    d = cs.to_dict()
    assert d == {"r": 255, "g": 180, "b": 60, "brightness": 80}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/projects/aether && source .venv/bin/activate && pytest tests/test_ramp.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'aether.lighting'`

- [ ] **Step 3: Write ramp module**

```python
# src/aether/lighting/__init__.py
```

```python
# src/aether/lighting/ramp.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator


@dataclass(frozen=True)
class ColorState:
    r: int
    g: int
    b: int
    brightness: int

    def to_dict(self) -> dict:
        return {"r": self.r, "g": self.g, "b": self.b, "brightness": self.brightness}


def interpolate(start: ColorState, end: ColorState, t: float) -> ColorState:
    """Linear interpolation between two color states. t in [0.0, 1.0]."""
    t = max(0.0, min(1.0, t))
    return ColorState(
        r=round(start.r + (end.r - start.r) * t),
        g=round(start.g + (end.g - start.g) * t),
        b=round(start.b + (end.b - start.b) * t),
        brightness=round(start.brightness + (end.brightness - start.brightness) * t),
    )


def generate_ramp(
    start: ColorState, end: ColorState, duration_sec: float, interval_ms: int
) -> Iterator[ColorState]:
    """Yield interpolated color states for a smooth ramp."""
    steps = int(duration_sec * 1000 / interval_ms)
    for i in range(steps):
        t = (i + 1) / steps
        yield interpolate(start, end, t)
```

- [ ] **Step 4: Run ramp tests**

Run: `cd ~/projects/aether && source .venv/bin/activate && pytest tests/test_ramp.py -v`

Expected: All 6 tests PASS.

- [ ] **Step 5: Write zones module**

```python
# src/aether/lighting/zones.py
from __future__ import annotations

from aether.lighting.ramp import ColorState


class ZoneManager:
    """Tracks current color state per zone and dispatches updates."""

    ZONE_NAMES = ("wall_left", "wall_right", "monitor", "floor", "bedroom")

    def __init__(self, govee_adapter):
        self._adapter = govee_adapter
        self._current: dict[str, ColorState] = {
            name: ColorState(r=0, g=0, b=0, brightness=0) for name in self.ZONE_NAMES
        }

    def get(self, zone: str) -> ColorState:
        return self._current[zone]

    def set_zone(self, zone: str, state: ColorState) -> None:
        self._current[zone] = state
        self._adapter.publish_zone(zone, state.to_dict())

    def set_all(self, state: ColorState) -> None:
        for zone in self.ZONE_NAMES:
            self.set_zone(zone, state)

    def get_all(self) -> dict[str, ColorState]:
        return dict(self._current)
```

- [ ] **Step 6: Commit**

```bash
git add src/aether/lighting/__init__.py src/aether/lighting/ramp.py src/aether/lighting/zones.py tests/test_ramp.py
git commit -m "feat: color ramp interpolation and zone management"
```

---

### Task 7: Circadian Engine

**Files:**
- Create: `src/aether/lighting/circadian.py`
- Create: `tests/test_circadian.py`

- [ ] **Step 1: Write failing circadian tests**

```python
# tests/test_circadian.py
from datetime import datetime, time, timezone, timedelta
import pytest
from aether.lighting.circadian import (
    SunTimes,
    compute_phase,
    phase_color,
    CircadianEngine,
)
from aether.lighting.ramp import ColorState


PALETTES = {
    "dawn": ColorState(r=255, g=160, b=50, brightness=30),
    "morning": ColorState(r=255, g=240, b=220, brightness=80),
    "midday": ColorState(r=255, g=255, b=255, brightness=100),
    "golden_hour": ColorState(r=255, g=180, b=60, brightness=70),
    "evening": ColorState(r=80, g=60, b=180, brightness=40),
    "night": ColorState(r=30, g=20, b=80, brightness=15),
    "nightlight": ColorState(r=180, g=140, b=60, brightness=5),
}

# Sunrise at 6:30, sunset at 19:00 (7 PM)
SUN = SunTimes(
    sunrise=datetime(2026, 3, 27, 6, 30, tzinfo=timezone.utc),
    sunset=datetime(2026, 3, 27, 19, 0, tzinfo=timezone.utc),
)


def test_dawn_phase():
    # 6:15 AM — 15 min before sunrise — should be dawn
    t = datetime(2026, 3, 27, 6, 15, tzinfo=timezone.utc)
    assert compute_phase(t, SUN) == "dawn"


def test_morning_phase():
    # 8:00 AM — well after sunrise + 30min
    t = datetime(2026, 3, 27, 8, 0, tzinfo=timezone.utc)
    assert compute_phase(t, SUN) == "morning"


def test_midday_phase():
    # 12:45 — solar noon is ~12:45
    t = datetime(2026, 3, 27, 12, 45, tzinfo=timezone.utc)
    assert compute_phase(t, SUN) == "midday"


def test_golden_hour_phase():
    # 18:00 — 1 hour before sunset
    t = datetime(2026, 3, 27, 18, 0, tzinfo=timezone.utc)
    assert compute_phase(t, SUN) == "golden_hour"


def test_evening_phase():
    # 19:30 — 30 min after sunset
    t = datetime(2026, 3, 27, 19, 30, tzinfo=timezone.utc)
    assert compute_phase(t, SUN) == "evening"


def test_night_phase():
    # 22:00 — well into night
    t = datetime(2026, 3, 27, 22, 0, tzinfo=timezone.utc)
    assert compute_phase(t, SUN) == "night"


def test_phase_color_returns_palette():
    color = phase_color("dawn", PALETTES)
    assert color == PALETTES["dawn"]


def test_fetch_sun_times_fallback():
    """If API fails, should return defaults."""
    from aether.lighting.circadian import get_default_sun_times
    defaults = get_default_sun_times()
    assert defaults.sunrise.hour == 6
    assert defaults.sunset.hour == 19
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/projects/aether && source .venv/bin/activate && pytest tests/test_circadian.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'aether.lighting.circadian'`

- [ ] **Step 3: Write circadian engine**

```python
# src/aether/lighting/circadian.py
from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from aether.config import AetherConfig, PaletteEntry
from aether.lighting.ramp import ColorState, generate_ramp
from aether.lighting.zones import ZoneManager
from aether.state import State


@dataclass
class SunTimes:
    sunrise: datetime
    sunset: datetime

    @property
    def solar_noon(self) -> datetime:
        return self.sunrise + (self.sunset - self.sunrise) / 2


CACHE_PATH = Path.home() / ".cache" / "aether" / "sun_times.json"


def get_default_sun_times() -> SunTimes:
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return SunTimes(
        sunrise=today.replace(hour=6, minute=0),
        sunset=today.replace(hour=19, minute=0),
    )


async def fetch_sun_times(lat: float, lon: float) -> SunTimes:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "daily": "sunrise,sunset",
                    "timezone": "auto",
                    "forecast_days": 1,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            sunrise_str = data["daily"]["sunrise"][0]
            sunset_str = data["daily"]["sunset"][0]

            sunrise = datetime.fromisoformat(sunrise_str)
            sunset = datetime.fromisoformat(sunset_str)

            # Cache for fallback
            CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            CACHE_PATH.write_text(json.dumps({
                "sunrise": sunrise.isoformat(),
                "sunset": sunset.isoformat(),
            }))

            return SunTimes(sunrise=sunrise, sunset=sunset)
    except Exception as e:
        print(f"[aether] Sunrise API failed: {e}. Trying cache...", file=sys.stderr)
        return _load_cached_or_default()


def _load_cached_or_default() -> SunTimes:
    try:
        data = json.loads(CACHE_PATH.read_text())
        return SunTimes(
            sunrise=datetime.fromisoformat(data["sunrise"]),
            sunset=datetime.fromisoformat(data["sunset"]),
        )
    except Exception:
        print("[aether] No cache. Using defaults (6:00 AM / 7:00 PM).", file=sys.stderr)
        return get_default_sun_times()


def compute_phase(now: datetime, sun: SunTimes) -> str:
    dawn_start = sun.sunrise - timedelta(minutes=30)
    dawn_end = sun.sunrise + timedelta(minutes=30)
    morning_end = sun.solar_noon - timedelta(hours=1)
    midday_end = sun.solar_noon + timedelta(hours=2)
    golden_start = sun.sunset - timedelta(hours=1, minutes=30)
    evening_end = sun.sunset + timedelta(hours=1, minutes=30)

    if dawn_start <= now < dawn_end:
        return "dawn"
    elif dawn_end <= now < morning_end:
        return "morning"
    elif morning_end <= now < midday_end:
        return "midday"
    elif golden_start <= now < sun.sunset:
        return "golden_hour"
    elif sun.sunset <= now < evening_end:
        return "evening"
    else:
        return "night"


def phase_color(phase: str, palettes: dict[str, ColorState]) -> ColorState:
    return palettes[phase]


def palettes_from_config(config: AetherConfig) -> dict[str, ColorState]:
    result = {}
    for name, entry in config.circadian.palettes.items():
        result[name] = ColorState(
            r=entry.color[0], g=entry.color[1], b=entry.color[2],
            brightness=entry.brightness,
        )
    return result


class CircadianEngine:
    def __init__(self, config: AetherConfig, zones: ZoneManager):
        self._config = config
        self._zones = zones
        self._palettes = palettes_from_config(config)
        self._sun: SunTimes | None = None
        self._last_fetch_date: str | None = None
        self._ramping = False
        self._state = State.PRESENT

    async def _ensure_sun_times(self) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._last_fetch_date == today and self._sun is not None:
            return

        loc = self._config.location
        if loc.latitude is not None and loc.longitude is not None:
            self._sun = await fetch_sun_times(loc.latitude, loc.longitude)
        else:
            self._sun = get_default_sun_times()
        self._last_fetch_date = today

    def on_state_change(self, new_state: State) -> None:
        self._state = new_state

    async def run_return_ramp(self) -> None:
        """8-second compressed sunrise ramp from nightlight to current circadian target."""
        if self._sun is None:
            return

        self._ramping = True
        nightlight = self._palettes.get("nightlight", ColorState(180, 140, 60, 5))
        now = datetime.now(timezone.utc)
        phase = compute_phase(now, self._sun)
        target = phase_color(phase, self._palettes)

        for step in generate_ramp(
            nightlight, target,
            duration_sec=self._config.circadian.return_ramp_sec,
            interval_ms=self._config.circadian.ramp_interval_ms,
        ):
            self._zones.set_all(step)
            await asyncio.sleep(self._config.circadian.ramp_interval_ms / 1000.0)

        self._ramping = False

    async def run(self) -> None:
        while True:
            if self._ramping:
                await asyncio.sleep(0.1)
                continue

            await self._ensure_sun_times()

            if self._state == State.AWAY:
                nightlight = self._palettes.get("nightlight", ColorState(180, 140, 60, 5))
                self._zones.set_all(nightlight)
            elif self._sun is not None:
                now = datetime.now(timezone.utc)
                phase = compute_phase(now, self._sun)
                target = phase_color(phase, self._palettes)
                self._zones.set_all(target)

            await asyncio.sleep(self._config.circadian.update_interval_sec)
```

- [ ] **Step 4: Run circadian tests**

Run: `cd ~/projects/aether && source .venv/bin/activate && pytest tests/test_circadian.py -v`

Expected: All 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aether/lighting/circadian.py tests/test_circadian.py
git commit -m "feat: circadian engine with sunrise API, phase computation, and ramps"
```

---

### Task 8: MQTT + Govee Adapter

**Files:**
- Create: `src/aether/adapters/__init__.py`
- Create: `src/aether/adapters/mqtt.py`
- Create: `src/aether/adapters/govee.py`
- Create: `tests/test_govee_adapter.py`

- [ ] **Step 1: Write failing adapter tests**

```python
# tests/test_govee_adapter.py
import json
from unittest.mock import MagicMock
from aether.adapters.govee import GoveeAdapter


def test_publish_zone_formats_topic():
    mqtt = MagicMock()
    zones_config = {
        "floor": MagicMock(govee_device="AA:BB:CC:DD:EE:FF"),
    }
    adapter = GoveeAdapter(mqtt, zones_config, topic_prefix="aether")

    adapter.publish_zone("floor", {"r": 255, "g": 180, "b": 0, "brightness": 100})

    mqtt.publish.assert_called_once()
    call_args = mqtt.publish.call_args
    assert call_args[0][0] == "aether/light/zone/floor"


def test_publish_zone_payload_is_json():
    mqtt = MagicMock()
    zones_config = {
        "wall_left": MagicMock(govee_device="11:22:33:44:55:66"),
    }
    adapter = GoveeAdapter(mqtt, zones_config, topic_prefix="aether")

    adapter.publish_zone("wall_left", {"r": 80, "g": 60, "b": 180, "brightness": 40})

    call_args = mqtt.publish.call_args
    payload = json.loads(call_args[0][1])
    assert payload["r"] == 80
    assert payload["g"] == 60
    assert payload["b"] == 180
    assert payload["brightness"] == 40


def test_publish_zone_skips_unconfigured():
    mqtt = MagicMock()
    zones_config = {
        "floor": MagicMock(govee_device=None),
    }
    adapter = GoveeAdapter(mqtt, zones_config, topic_prefix="aether")

    adapter.publish_zone("floor", {"r": 255, "g": 0, "b": 0, "brightness": 100})
    mqtt.publish.assert_not_called()


def test_publish_state():
    mqtt = MagicMock()
    adapter = GoveeAdapter(mqtt, {}, topic_prefix="aether")

    adapter.publish_state("away")
    mqtt.publish.assert_called_once_with("aether/state", '"away"', retain=True)


def test_publish_transition():
    mqtt = MagicMock()
    adapter = GoveeAdapter(mqtt, {}, topic_prefix="aether")

    adapter.publish_transition("present", "away", "human_absent")
    call_args = mqtt.publish.call_args
    assert call_args[0][0] == "aether/state/transition"
    payload = json.loads(call_args[0][1])
    assert payload["from"] == "present"
    assert payload["to"] == "away"
    assert payload["reason"] == "human_absent"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/projects/aether && source .venv/bin/activate && pytest tests/test_govee_adapter.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'aether.adapters'`

- [ ] **Step 3: Write MQTT wrapper**

```python
# src/aether/adapters/__init__.py
```

```python
# src/aether/adapters/mqtt.py
from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

import paho.mqtt.client as paho_mqtt


class MqttClient:
    def __init__(self, broker: str = "localhost", port: int = 1883):
        self._broker = broker
        self._port = port
        self._client = paho_mqtt.Client(paho_mqtt.CallbackAPIVersion.VERSION2)
        self._connected = False
        self._buffer: list[tuple[str, str, bool]] = []
        self._max_buffer = 10

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            self._connected = True
            print(f"[aether] MQTT connected to {self._broker}:{self._port}", file=sys.stderr)
            self._flush_buffer()
        else:
            print(f"[aether] MQTT connection failed: rc={rc}", file=sys.stderr)

    def _on_disconnect(self, client, userdata, flags, rc, properties=None):
        self._connected = False
        print(f"[aether] MQTT disconnected: rc={rc}", file=sys.stderr)

    def _flush_buffer(self):
        for topic, payload, retain in self._buffer:
            self._client.publish(topic, payload, qos=1, retain=retain)
        self._buffer.clear()

    def publish(self, topic: str, payload: Any, retain: bool = False) -> None:
        if isinstance(payload, (dict, list)):
            payload = json.dumps(payload)
        elif not isinstance(payload, str):
            payload = json.dumps(payload)

        if self._connected:
            self._client.publish(topic, payload, qos=1, retain=retain)
        else:
            if len(self._buffer) >= self._max_buffer:
                self._buffer.pop(0)
            self._buffer.append((topic, payload, retain))

    async def run(self) -> None:
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect

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

    def disconnect(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()
```

- [ ] **Step 4: Write Govee adapter**

```python
# src/aether/adapters/govee.py
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


class GoveeAdapter:
    """Translates Aether zone commands to MQTT messages for govee2mqtt."""

    def __init__(self, mqtt_client, zones_config: dict, topic_prefix: str = "aether"):
        self._mqtt = mqtt_client
        self._zones = zones_config
        self._prefix = topic_prefix

    def publish_zone(self, zone: str, color: dict) -> None:
        zone_cfg = self._zones.get(zone)
        if zone_cfg is None or zone_cfg.govee_device is None:
            return

        topic = f"{self._prefix}/light/zone/{zone}"
        self._mqtt.publish(topic, color, retain=True)

    def publish_state(self, state: str) -> None:
        self._mqtt.publish(f"{self._prefix}/state", json.dumps(state), retain=True)

    def publish_transition(self, from_state: str, to_state: str, reason: str) -> None:
        payload = {
            "from": from_state,
            "to": to_state,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._mqtt.publish(f"{self._prefix}/state/transition", json.dumps(payload), retain=False)

    def publish_presence(self, human: bool) -> None:
        self._mqtt.publish(f"{self._prefix}/presence/human", json.dumps(human), retain=True)
        if human:
            self._mqtt.publish(
                f"{self._prefix}/presence/last_seen",
                json.dumps(datetime.now(timezone.utc).isoformat()),
                retain=True,
            )
```

- [ ] **Step 5: Run adapter tests**

Run: `cd ~/projects/aether && source .venv/bin/activate && pytest tests/test_govee_adapter.py -v`

Expected: All 5 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/aether/adapters/__init__.py src/aether/adapters/mqtt.py src/aether/adapters/govee.py tests/test_govee_adapter.py
git commit -m "feat: MQTT client wrapper and Govee adapter for zone control"
```

---

### Task 9: Main Daemon + CLI

**Files:**
- Create: `src/aether/__main__.py`
- Create: `src/aether/cli.py`

- [ ] **Step 1: Write __main__.py**

```python
# src/aether/__main__.py
from aether.cli import cli

if __name__ == "__main__":
    cli()
```

- [ ] **Step 2: Write cli.py with run command**

```python
# src/aether/cli.py
from __future__ import annotations

import asyncio
import sys

import click

from aether.config import load_config
from aether.state import StateMachine, State, Transition
from aether.vision.camera import Camera
from aether.vision.presence import PresenceDetector
from aether.lighting.circadian import CircadianEngine
from aether.lighting.zones import ZoneManager
from aether.adapters.mqtt import MqttClient
from aether.adapters.govee import GoveeAdapter
from aether.alerts.sentry import SentryAlert


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

    def handle_transition(t: Transition):
        nonlocal alert_task
        print(f"[aether] {t.from_state.value} → {t.to_state.value} ({t.reason})", file=sys.stderr)
        adapter.publish_state(t.to_state.value)
        adapter.publish_transition(t.from_state.value, t.to_state.value, t.reason)
        circadian.on_state_change(t.to_state)

        if t.to_state == State.PRESENT and t.from_state == State.AWAY:
            asyncio.ensure_future(circadian.run_return_ramp())

    state_machine._on_transition = handle_transition

    # Wrap presence to also publish MQTT + trigger sentry
    original_update = presence.tracker.update

    def update_with_mqtt(human_detected: bool, now: float | None = None):
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
        camera.release()
        mqtt.disconnect()


@cli.command()
def status():
    """Show current Aether state (reads from MQTT retained messages)."""
    import json
    import paho.mqtt.client as paho_mqtt

    results = {}
    topics = [
        "aether/state",
        "aether/presence/human",
        "aether/presence/last_seen",
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
```

- [ ] **Step 3: Verify CLI loads**

Run: `cd ~/projects/aether && source .venv/bin/activate && python -m aether --help`

Expected:
```
Usage: python -m aether [OPTIONS] COMMAND [ARGS]...

  Aether — The Living Room

Options:
  --help  Show this message and exit.

Commands:
  run     Start the Aether daemon.
  status  Show current Aether state (reads from MQTT retained messages).
```

- [ ] **Step 4: Commit**

```bash
git add src/aether/__main__.py src/aether/cli.py
git commit -m "feat: CLI with run and status commands, main daemon loop"
```

---

### Task 10: Discover Command

**Files:**
- Modify: `src/aether/cli.py`

- [ ] **Step 1: Add discover command to cli.py**

Append this command to `cli.py` after the `status` command:

```python
@cli.command()
@click.option("--config", "config_path", type=click.Path(), default=None, help="Config file path")
def discover(config_path):
    """Discover Govee devices and map them to zones."""
    import json
    import time
    from pathlib import Path
    import paho.mqtt.client as paho_mqtt
    import yaml

    path = Path(config_path) if config_path else None
    config = load_config(path)
    config_file = path or load_config.__defaults__[0] if path else Path.home() / ".config" / "aether" / "config.yaml"

    devices = {}

    def on_connect(client, userdata, flags, rc, properties=None):
        client.subscribe("homeassistant/light/govee2mqtt/#")

    def on_message(client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
            if "name" in payload and "unique_id" in payload:
                dev_id = payload["unique_id"]
                devices[dev_id] = {
                    "name": payload.get("name", "Unknown"),
                    "id": dev_id,
                    "topic": msg.topic,
                }
        except (json.JSONDecodeError, KeyError):
            pass

    client = paho_mqtt.Client(paho_mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(config.mqtt.broker, config.mqtt.port)
    except Exception as e:
        click.echo(f"Cannot connect to MQTT: {e}", err=True)
        sys.exit(1)

    click.echo("Scanning for Govee devices via govee2mqtt (5 seconds)...")
    client.loop_start()
    time.sleep(5)
    client.loop_stop()

    if not devices:
        click.echo("No Govee devices found. Is govee2mqtt running?")
        sys.exit(1)

    dev_list = list(devices.values())
    click.echo(f"\nFound {len(dev_list)} Govee devices:")
    for i, dev in enumerate(dev_list, 1):
        click.echo(f"  {i}. {dev['name']} ({dev['id']})")

    zone_names = ["wall_left", "wall_right", "monitor", "floor", "bedroom"]
    zone_map = {}

    click.echo("\nMap devices to zones (enter number, or 0 to skip):")
    for zone in zone_names:
        while True:
            choice = click.prompt(f"  {zone}", type=int, default=0)
            if choice == 0:
                break
            if 1 <= choice <= len(dev_list):
                zone_map[zone] = dev_list[choice - 1]["id"]
                break
            click.echo(f"  Invalid choice. Enter 1-{len(dev_list)} or 0 to skip.")

    # Write back to config
    config_file_path = path or (Path.home() / ".config" / "aether" / "config.yaml")
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

- [ ] **Step 2: Verify discover shows in help**

Run: `cd ~/projects/aether && source .venv/bin/activate && python -m aether --help`

Expected: Commands list now includes `discover`.

- [ ] **Step 3: Commit**

```bash
git add src/aether/cli.py
git commit -m "feat: add discover command for Govee device-to-zone mapping"
```

---

### Task 11: Systemd + CLAUDE.md + Final Wiring

**Files:**
- Create: `systemd/aether.service`
- Create: `CLAUDE.md`

- [ ] **Step 1: Create systemd unit**

```ini
# systemd/aether.service
[Unit]
Description=Aether - Living Room Daemon
After=mosquitto.service
Wants=mosquitto.service

[Service]
Type=simple
ExecStart=%h/projects/aether/.venv/bin/python -m aether run
WorkingDirectory=%h/projects/aether
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
```

- [ ] **Step 2: Create CLAUDE.md**

```markdown
# aether

Room-scale presence-aware circadian lighting daemon.

## Tech Stack

- **Python 3.11+** — single async process
- **MediaPipe** — human pose detection (CPU-only, dogs ignored)
- **OpenCV** (headless) — camera capture
- **paho-mqtt** — MQTT client
- **Pydantic** — config validation
- **httpx** — sunrise/sunset API
- **Click** — CLI framework

## External Dependencies

- **mosquitto** — MQTT broker (`systemctl --user start mosquitto`)
- **govee2mqtt** — Govee device bridge

## Commands

```bash
# Development
source .venv/bin/activate
python -m aether run              # Start daemon
python -m aether discover         # Map Govee devices to zones
python -m aether status           # Check current state
pytest                            # Run tests

# Systemd
systemctl --user enable aether
systemctl --user start aether
journalctl --user -u aether -f   # View logs
```

## Architecture

Single Python async process: C920 → MediaPipe pose → state machine (PRESENT/AWAY) → circadian engine → MQTT → govee2mqtt → Govee lights.

## Config

`~/.config/aether/config.yaml` — copy from `config.example.yaml`.
Set `location.latitude` and `location.longitude` for sunrise/sunset times.
Run `aether discover` to map Govee devices to zones.

## Design Spec

`docs/superpowers/specs/2026-03-27-aether-design.md`
```

- [ ] **Step 3: Run full test suite**

Run: `cd ~/projects/aether && source .venv/bin/activate && pytest -v`

Expected: All tests pass (config: 5, state: 6, presence: 5, ramp: 6, circadian: 8, govee_adapter: 5 = 35 total).

- [ ] **Step 4: Commit**

```bash
git add systemd/aether.service CLAUDE.md
git commit -m "feat: systemd service unit and project context docs"
```

- [ ] **Step 5: Final integration commit**

Run all tests one more time, then tag:

```bash
pytest -v && git tag v0.1.0
```

---

## Spec Coverage Checklist

| Spec Requirement | Task |
|-----------------|------|
| C920 → MediaPipe human pose (CPU, dogs ignored) | Task 4, 5 |
| State machine: PRESENT ↔ AWAY (10s timer) | Task 3, 5 |
| Circadian Forge: sunrise/sunset API + config palettes | Task 7 |
| Govee control via MQTT → govee2mqtt (5 devices) | Task 8 |
| Compressed sunrise return ramp (8s) | Task 6, 7 |
| AWAY alerts: log + floor flash | Task 5 |
| Config: YAML + Pydantic validation | Task 2 |
| `aether discover` CLI | Task 10 |
| `aether status` CLI | Task 9 |
| Systemd user service | Task 11 |
| Graceful degradation (camera retry, MQTT buffer, API fallback) | Task 4, 8, 7 |
| MQTT topic contract (retained messages) | Task 8, 9 |
| Resource budget (<2% CPU, <300MB RAM) | Task 4 (640x480, 3fps), Task 5 (model_complexity=0) |
| Phase 2+ features tracked | Spec doc (not in plan — by design) |
