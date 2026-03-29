# Aether Phase 3 Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add priority mixer for zone claim arbitration, Vox voice commands (wake word + STT + intent), and hand gesture detection (thumbs up/down, fist hold) to Aether.

**Architecture:** A priority mixer replaces direct ZoneManager writes — all systems submit claims with priority levels and optional TTLs. Voice commands flow through UM02 mic → openWakeWord → faster-whisper → keyword/Ollama intent classifier. Hand gestures use MediaPipe HandLandmarker on existing camera frames. Both voice and gestures submit manual-priority claims to the mixer.

**Tech Stack:** Python 3.14, asyncio, faster-whisper (new), openwakeword (new), MediaPipe hands (included), Ollama qwen3.5:4b (existing), existing paho-mqtt/Pydantic/Click stack.

**Spec:** `docs/superpowers/specs/2026-03-28-aether-phase3-core-design.md`

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `src/aether/mixer.py` | Priority claim registry, per-zone resolution, TTL expiry tick loop |
| `src/aether/vox/__init__.py` | Vox package init |
| `src/aether/vox/mic.py` | PipeWire capture from UM02 via pw-cat subprocess |
| `src/aether/vox/wake.py` | openWakeWord wake word detector wrapping audio stream |
| `src/aether/vox/stt.py` | faster-whisper transcription (GPU, on-demand loading) |
| `src/aether/vox/intent.py` | Keyword matcher + Ollama fallback classifier |
| `src/aether/vox/handler.py` | Intent → action execution (mixer claims, state machine events) |
| `src/aether/vision/gestures.py` | HandLandmarker setup, gesture classifier, debounce/cooldown |
| `tests/test_mixer.py` | Claim submission, resolution, priority, expiry |
| `tests/test_intent.py` | Keyword matching, fallback handling |
| `tests/test_gestures.py` | Gesture classification, debounce, cooldown |

### Modified Files

| File | Changes |
|------|---------|
| `src/aether/config.py` | Add MixerConfig, VoxConfig, GestureConfig models |
| `src/aether/lighting/circadian.py` | Accept mixer instead of zones, submit claims |
| `src/aether/modes/focus.py` | Accept mixer instead of zones, submit claims |
| `src/aether/modes/sleep.py` | Accept mixer instead of zones, submit claims |
| `src/aether/modes/dj.py` | Accept mixer instead of zones, submit claims |
| `src/aether/vision/presence.py` | Run HandLandmarker alongside PoseLandmarker |
| `src/aether/cli.py` | Wire mixer, vox pipeline, gestures into daemon; add vox-test; extend status |
| `config.example.yaml` | Add mixer, vox, gestures sections |
| `pyproject.toml` | Add faster-whisper, openwakeword |
| `CLAUDE.md` | Add Phase 3 commands and architecture |

---

### Task 1: Add Config Models

**Files:**
- Modify: `src/aether/config.py`
- Modify: `config.example.yaml`
- Create: `tests/test_config_phase3.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_config_phase3.py`:

```python
from aether.config import AetherConfig, MixerConfig, VoxConfig, GestureConfig


def test_mixer_config_defaults():
    cfg = MixerConfig()
    assert cfg.manual_ttl_sec == 600
    assert cfg.tick_interval_sec == 1


def test_vox_config_defaults():
    cfg = VoxConfig()
    assert cfg.enabled is True
    assert cfg.wake_word == "aether"
    assert cfg.command_timeout_sec == 5
    assert cfg.silence_timeout_sec == 1.5
    assert cfg.whisper_model == "small"
    assert cfg.ollama_model == "qwen3.5:4b"
    assert cfg.feedback_flash is True
    assert "UM02" in cfg.mic_source


def test_gesture_config_defaults():
    cfg = GestureConfig()
    assert cfg.enabled is True
    assert cfg.detection_confidence == 0.5
    assert cfg.consecutive_frames == 3
    assert cfg.fist_hold_frames == 9
    assert cfg.cooldown_sec == 5
    assert cfg.feedback_flash is True


def test_aether_config_includes_phase3():
    cfg = AetherConfig()
    assert isinstance(cfg.mixer, MixerConfig)
    assert isinstance(cfg.vox, VoxConfig)
    assert isinstance(cfg.gestures, GestureConfig)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/digitalghost/projects/aether && .venv/bin/pytest tests/test_config_phase3.py -v`
Expected: FAIL — `MixerConfig` not importable

- [ ] **Step 3: Add config models**

Add after `SleepConfig` in `src/aether/config.py`:

```python
class MixerConfig(BaseModel):
    manual_ttl_sec: int = 600
    tick_interval_sec: int = 1


class VoxConfig(BaseModel):
    enabled: bool = True
    mic_source: str = "alsa_input.usb-Clip-on_USB_microphone_UM02-00.mono-fallback"
    wake_word: str = "aether"
    command_timeout_sec: int = 5
    silence_timeout_sec: float = 1.5
    whisper_model: str = "small"
    ollama_model: str = "qwen3.5:4b"
    feedback_flash: bool = True


class GestureConfig(BaseModel):
    enabled: bool = True
    detection_confidence: float = 0.5
    consecutive_frames: int = 3
    fist_hold_frames: int = 9
    cooldown_sec: int = 5
    feedback_flash: bool = True
```

Update `AetherConfig`:

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
    mixer: MixerConfig = MixerConfig()
    vox: VoxConfig = VoxConfig()
    gestures: GestureConfig = GestureConfig()
```

- [ ] **Step 4: Update config.example.yaml**

Append after the `sleep` section:

```yaml

mixer:
  manual_ttl_sec: 600          # 10 min default for voice/gesture overrides
  tick_interval_sec: 1         # claim expiry check rate

vox:
  enabled: true
  mic_source: "alsa_input.usb-Clip-on_USB_microphone_UM02-00.mono-fallback"
  wake_word: "aether"
  command_timeout_sec: 5
  silence_timeout_sec: 1.5
  whisper_model: "small"
  ollama_model: "qwen3.5:4b"
  feedback_flash: true

gestures:
  enabled: true
  detection_confidence: 0.5
  consecutive_frames: 3
  fist_hold_frames: 9
  cooldown_sec: 5
  feedback_flash: true
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/digitalghost/projects/aether && .venv/bin/pytest tests/test_config_phase3.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
cd /home/digitalghost/projects/aether
git add src/aether/config.py config.example.yaml tests/test_config_phase3.py
git commit -m "feat: add Mixer, Vox, Gesture config models"
```

---

### Task 2: Implement Priority Mixer

**Files:**
- Create: `src/aether/mixer.py`
- Create: `tests/test_mixer.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_mixer.py`:

```python
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
    # Last call should be blue (priority 0 beats priority 2)
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
    # Both zones should fall back to circadian (red)
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
    assert len(zm.calls) == 5  # all 5 zones


def test_ttl_expiry():
    zm = FakeZoneManager()
    mixer = Mixer(zm)
    red = ColorState(r=255, g=0, b=0, brightness=100)
    blue = ColorState(r=0, g=0, b=255, brightness=100)
    mixer.submit("circadian", "floor", red, priority=2)
    # Submit with TTL of 0 seconds (already expired)
    mixer.submit("voice", "floor", blue, priority=0, ttl_sec=0)
    mixer.expire_claims()
    mixer.resolve()
    floor_calls = [c for c in zm.calls if c[0] == "floor"]
    assert floor_calls[-1][1] == red  # voice expired, circadian wins


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
    assert len(zm.calls) == 0  # paused, no forwarding


def test_same_source_updates_claim():
    zm = FakeZoneManager()
    mixer = Mixer(zm)
    red = ColorState(r=255, g=0, b=0, brightness=100)
    blue = ColorState(r=0, g=0, b=255, brightness=100)
    mixer.submit("circadian", "floor", red, priority=2)
    mixer.submit("circadian", "floor", blue, priority=2)
    mixer.resolve()
    floor_calls = [c for c in zm.calls if c[0] == "floor"]
    assert floor_calls[-1][1] == blue  # updated, not stacked
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/digitalghost/projects/aether && .venv/bin/pytest tests/test_mixer.py -v`
Expected: FAIL — `cannot import Mixer`

- [ ] **Step 3: Implement Mixer**

Create `src/aether/mixer.py`:

```python
from __future__ import annotations

import asyncio
import sys
import time
from dataclasses import dataclass, field

from aether.lighting.ramp import ColorState
from aether.lighting.zones import ZoneManager


@dataclass
class Claim:
    source: str
    zone: str
    color: ColorState
    priority: int
    ttl_sec: float | None = None
    created_at: float = field(default_factory=time.monotonic)


class Mixer:
    def __init__(self, zones: ZoneManager):
        self._zones = zones
        # zone -> source -> Claim
        self._claims: dict[str, dict[str, Claim]] = {}
        # Track last resolved color per zone to avoid duplicate writes
        self._last_resolved: dict[str, ColorState] = {}

    def submit(self, source: str, zone: str, color: ColorState, priority: int, ttl_sec: float | None = None) -> None:
        if zone not in self._claims:
            self._claims[zone] = {}
        self._claims[zone][source] = Claim(
            source=source,
            zone=zone,
            color=color,
            priority=priority,
            ttl_sec=ttl_sec,
            created_at=time.monotonic(),
        )

    def submit_all(self, source: str, color: ColorState, priority: int, ttl_sec: float | None = None) -> None:
        for zone in ZoneManager.ZONE_NAMES:
            self.submit(source, zone, color, priority, ttl_sec)

    def release(self, source: str, zone: str) -> None:
        if zone in self._claims:
            self._claims[zone].pop(source, None)

    def release_all(self, source: str) -> None:
        for zone in list(self._claims):
            self._claims[zone].pop(source, None)

    def expire_claims(self) -> None:
        now = time.monotonic()
        for zone in list(self._claims):
            for source in list(self._claims[zone]):
                claim = self._claims[zone][source]
                if claim.ttl_sec is not None:
                    if now - claim.created_at >= claim.ttl_sec:
                        del self._claims[zone][source]

    def _resolve_zone(self, zone: str) -> ColorState | None:
        claims = self._claims.get(zone, {})
        if not claims:
            return None
        # Lowest priority number wins; ties broken by most recent
        winner = min(claims.values(), key=lambda c: (c.priority, -c.created_at))
        return winner.color

    def resolve(self) -> None:
        if self._zones.paused:
            return
        for zone in ZoneManager.ZONE_NAMES:
            color = self._resolve_zone(zone)
            if color is not None:
                if self._last_resolved.get(zone) != color:
                    self._last_resolved[zone] = color
                    self._zones.set_zone(zone, color)

    def get_active_claims(self) -> dict[str, Claim]:
        result = {}
        for zone in ZoneManager.ZONE_NAMES:
            claims = self._claims.get(zone, {})
            if claims:
                winner = min(claims.values(), key=lambda c: (c.priority, -c.created_at))
                result[zone] = winner
        return result

    async def run(self, tick_interval: float = 1.0) -> None:
        while True:
            self.expire_claims()
            self.resolve()
            await asyncio.sleep(tick_interval)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/digitalghost/projects/aether && .venv/bin/pytest tests/test_mixer.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
cd /home/digitalghost/projects/aether
git add src/aether/mixer.py tests/test_mixer.py
git commit -m "feat: implement priority mixer with claim-based zone arbitration"
```

---

### Task 3: Refactor Existing Code to Use Mixer

**Files:**
- Modify: `src/aether/lighting/circadian.py`
- Modify: `src/aether/modes/focus.py`
- Modify: `src/aether/modes/sleep.py`
- Modify: `src/aether/modes/dj.py`

This is the mechanical refactor: replace all `self._zones.set_zone()` and `self._zones.set_all()` calls with mixer submissions. Modes use priority 1, circadian uses priority 2.

- [ ] **Step 1: Refactor CircadianEngine**

In `src/aether/lighting/circadian.py`:

Change the constructor to accept a mixer:

```python
class CircadianEngine:
    def __init__(self, config: AetherConfig, mixer):
        self._config = config
        self._mixer = mixer
        self._palettes = palettes_from_config(config)
        self._sun: SunTimes | None = None
        self._last_fetch_date: str | None = None
        self._ramping = False
        self._state = State.PRESENT
```

Remove the `ZoneManager` import. Add the `Mixer` usage:

Replace `on_state_change`:

```python
    def on_state_change(self, new_state: State) -> None:
        self._state = new_state
        if new_state == State.AWAY:
            nightlight = self._palettes.get("nightlight", ColorState(180, 140, 60, 5))
            self._mixer.submit_all("circadian", nightlight, priority=2)
            self._mixer.resolve()
```

Replace `run_return_ramp`:

```python
    async def run_return_ramp(self) -> None:
        if self._sun is None:
            return

        self._ramping = True
        nightlight = self._palettes.get("nightlight", ColorState(180, 140, 60, 5))
        now = datetime.now()
        phase = compute_phase(now, self._sun)
        target = phase_color(phase, self._palettes)

        ramp_steps = 8
        step_interval = self._config.circadian.return_ramp_sec / ramp_steps

        for step in generate_ramp(
            nightlight, target,
            duration_sec=self._config.circadian.return_ramp_sec,
            interval_ms=int(step_interval * 1000),
        ):
            self._mixer.submit_all("circadian", step, priority=2)
            self._mixer.resolve()
            await asyncio.sleep(step_interval)

        self._ramping = False
```

Replace the `run` loop body:

```python
    async def run(self) -> None:
        while True:
            if self._ramping:
                await asyncio.sleep(0.1)
                continue

            await self._ensure_sun_times()

            if self._state == State.AWAY:
                nightlight = self._palettes.get("nightlight", ColorState(180, 140, 60, 5))
                self._mixer.submit_all("circadian", nightlight, priority=2)
            elif self._state == State.PRESENT and self._sun is not None:
                now = datetime.now()
                phase = compute_phase(now, self._sun)
                target = phase_color(phase, self._palettes)
                self._mixer.submit_all("circadian", target, priority=2)

            await asyncio.sleep(self._config.circadian.update_interval_sec)
```

Note: the circadian engine no longer calls `resolve()` in the tick loop — the mixer's own `run()` tick handles resolution. The explicit `resolve()` calls in `on_state_change` and `run_return_ramp` are for immediate effect.

- [ ] **Step 2: Refactor FocusMode**

In `src/aether/modes/focus.py`, change the constructor to accept a mixer:

```python
class FocusMode:
    def __init__(
        self,
        config: FocusConfig,
        mixer,
        cancel: asyncio.Event,
        pause: asyncio.Event,
    ):
        self._config = config
        self._mixer = mixer
        self._cancel = cancel
        self._pause = pause
        self.phase = PomodoroPhase.WORK
        self.cycle = 1
        self._total_cycles = config.cycles
        self._work_in_cycle = 0
```

Replace all `self._zones.set_zone(zone, color)` calls with `self._mixer.submit("focus", zone, color, priority=1)`. Replace all `self._zones.set_all(color)` calls with `self._mixer.submit_all("focus", color, priority=1)`.

In `_apply_work_lighting`:

```python
    def _apply_work_lighting(self, progress: float) -> None:
        cfg = self._config
        self._mixer.submit(
            "focus", "monitor",
            ColorState(r=cfg.work_color[0], g=cfg.work_color[1], b=cfg.work_color[2], brightness=cfg.work_brightness),
            priority=1,
        )
        rope_br = self._rope_brightness(progress)
        rope_color = ColorState(r=180, g=140, b=60, brightness=rope_br)
        self._mixer.submit("focus", "wall_left", rope_color, priority=1)
        self._mixer.submit("focus", "wall_right", rope_color, priority=1)
        off = ColorState(r=0, g=0, b=0, brightness=0)
        self._mixer.submit("focus", "floor", off, priority=1)
        self._mixer.submit("focus", "bedroom", off, priority=1)
        self._mixer.resolve()
```

In `_apply_break_lighting`:

```python
    def _apply_break_lighting(self) -> None:
        cfg = self._config
        self._mixer.submit(
            "focus", "monitor",
            ColorState(r=cfg.work_color[0], g=cfg.work_color[1], b=cfg.work_color[2], brightness=60),
            priority=1,
        )
        break_color = ColorState(
            r=cfg.break_color[0], g=cfg.break_color[1], b=cfg.break_color[2],
            brightness=cfg.break_brightness,
        )
        self._mixer.submit("focus", "wall_left", break_color, priority=1)
        self._mixer.submit("focus", "wall_right", break_color, priority=1)
        off = ColorState(r=0, g=0, b=0, brightness=0)
        self._mixer.submit("focus", "floor", off, priority=1)
        self._mixer.submit("focus", "bedroom", off, priority=1)
        self._mixer.resolve()
```

In `_apply_long_break_lighting`:

```python
    def _apply_long_break_lighting(self) -> None:
        cfg = self._config
        self._mixer.submit(
            "focus", "monitor",
            ColorState(r=cfg.work_color[0], g=cfg.work_color[1], b=cfg.work_color[2], brightness=60),
            priority=1,
        )
        amber = ColorState(r=255, g=180, b=60, brightness=70)
        self._mixer.submit("focus", "wall_left", amber, priority=1)
        self._mixer.submit("focus", "wall_right", amber, priority=1)
        off = ColorState(r=0, g=0, b=0, brightness=0)
        self._mixer.submit("focus", "floor", off, priority=1)
        self._mixer.submit("focus", "bedroom", off, priority=1)
        self._mixer.resolve()
```

In `_flash_ropes`:

```python
    async def _flash_ropes(self, count: int = 2) -> None:
        bright = ColorState(r=255, g=255, b=255, brightness=100)
        dim = ColorState(r=180, g=140, b=60, brightness=self._config.rope_dim_brightness)
        for _ in range(count):
            self._mixer.submit("focus", "wall_left", bright, priority=1)
            self._mixer.submit("focus", "wall_right", bright, priority=1)
            self._mixer.resolve()
            await asyncio.sleep(0.3)
            self._mixer.submit("focus", "wall_left", dim, priority=1)
            self._mixer.submit("focus", "wall_right", dim, priority=1)
            self._mixer.resolve()
            await asyncio.sleep(0.3)
```

Add cleanup in `run()`:

```python
    async def run(self) -> None:
        try:
            # ... existing loop unchanged ...
        finally:
            self._mixer.release_all("focus")
            self._mixer.resolve()
            print("[aether] FOCUS: ended", file=sys.stderr)
```

- [ ] **Step 3: Refactor SleepMode**

In `src/aether/modes/sleep.py`, change the constructor:

```python
class SleepMode:
    # ... STAGE_FRACTIONS unchanged ...

    def __init__(
        self,
        config: SleepConfig,
        mixer,
        mqtt,
        cancel: asyncio.Event,
        pause: asyncio.Event,
    ):
        self._config = config
        self._mixer = mixer
        self._mqtt = mqtt
        self._cancel = cancel
        self._pause = pause
        self.stage = SleepStage.MONITOR
        self.completed = False
```

In `_fade_zone`, replace zone access:

```python
    async def _fade_zone(self, zone: str, target: ColorState, duration_sec: float) -> bool:
        start = self._mixer.get_active_claims().get(zone)
        start_color = start.color if start else ColorState(r=255, g=255, b=255, brightness=100)
        if duration_sec <= 0:
            self._mixer.submit("sleep", zone, target, priority=1)
            self._mixer.resolve()
            return self._cancel.is_set()

        step_count = max(1, int(duration_sec / 12))
        interval = duration_sec / step_count

        for step in generate_ramp(start_color, target, duration_sec, int(interval * 1000)):
            if self._cancel.is_set():
                return True
            while self._pause.is_set():
                await asyncio.sleep(0.5)
                if self._cancel.is_set():
                    return True
            self._mixer.submit("sleep", zone, step, priority=1)
            self._mixer.resolve()
            await asyncio.sleep(interval)

        self._mixer.submit("sleep", zone, target, priority=1)
        self._mixer.resolve()
        return False
```

Add cleanup at the end of `run()` — after the cascade completes, don't release claims (lights should stay off). On cancel, release:

In the `run()` method, the existing structure stays the same but ensure that on `return` (cancel), we clean up:

```python
    async def run(self) -> None:
        total_sec = self._config.total_duration_min * 60
        off = ColorState(r=0, g=0, b=0, brightness=0)

        try:
            # ... existing cascade stages unchanged (they now use self._mixer) ...

            # Complete
            self.stage = SleepStage.COMPLETE
            self._publish_stage(self.stage)
            self.completed = True
            print("[aether] SLEEP: cascade complete", file=sys.stderr)

        except Exception as e:
            print(f"[aether] SLEEP error: {e}", file=sys.stderr)
        finally:
            if not self.completed:
                # Cancelled — release claims so circadian can resume
                self._mixer.release_all("sleep")
                self._mixer.resolve()
```

- [ ] **Step 4: Refactor DJMode**

In `src/aether/modes/dj.py`, change the constructor to accept mixer:

```python
class DJMode:
    def __init__(
        self,
        config: PartyConfig,
        mixer,
        mqtt,
        cancel: asyncio.Event,
        pause: asyncio.Event,
    ):
        self._config = config
        self._mixer = mixer
        self._mqtt = mqtt
        self._cancel = cancel
        self._pause = pause
        self._analyzer = BeatAnalyzer()
        self._palette_index = 0
        self._accent_high = False
        self._beats_since_shift = 0
        self._current_base_color: tuple[int, int, int] = tuple(config.palette[0]) if config.palette else (128, 0, 255)
        self._last_sound_time = time.monotonic()
```

Replace `_apply_base_color`:

```python
    def _apply_base_color(self, r: int, g: int, b: int, brightness: int = 80) -> None:
        color = ColorState(r=r, g=g, b=b, brightness=brightness)
        for zone in ("wall_left", "wall_right", "monitor", "bedroom"):
            self._mixer.submit("party", zone, color, priority=1)
        self._mixer.resolve()
```

Replace `_apply_accent`:

```python
    def _apply_accent(self, brightness: int) -> None:
        r, g, b = self._current_base_color
        accent = ColorState(r=r, g=g, b=b, brightness=brightness)
        self._mixer.submit("party", self._config.accent_zone, accent, priority=1)
        self._mixer.resolve()
```

Add cleanup in the `finally` block of `run()`:

```python
        finally:
            if proc and proc.poll() is None:
                proc.terminate()
                proc.wait()
            self._mixer.release_all("party")
            self._mixer.resolve()
            print("[aether] PARTY: ended", file=sys.stderr)
```

- [ ] **Step 5: Update existing tests**

Update `tests/test_focus.py` — change `FakeZoneManager` to a `FakeMixer`:

```python
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
```

Update `make_focus` to pass `FakeMixer`:

```python
def make_focus(config=None, mixer=None):
    cfg = config or FocusConfig(work_min=1, short_break_min=1, long_break_min=1, cycles=2)
    mx = mixer or FakeMixer()
    cancel = asyncio.Event()
    pause = asyncio.Event()
    return FocusMode(cfg, mx, cancel, pause), mx, cancel
```

Update `test_apply_work_lighting` to check mixer submissions:

```python
def test_apply_work_lighting():
    mode, mx, _ = make_focus()
    mode._apply_work_lighting(progress=0.0)
    monitor_subs = [(s, z, c, p) for s, z, c, p in mx.submissions if z == "monitor"]
    assert len(monitor_subs) == 1
    assert monitor_subs[0][2] == ColorState(r=255, g=255, b=255, brightness=100)
    floor_subs = [(s, z, c, p) for s, z, c, p in mx.submissions if z == "floor"]
    assert floor_subs[0][2] == ColorState(r=0, g=0, b=0, brightness=0)
    rope_subs = [(s, z, c, p) for s, z, c, p in mx.submissions if z == "wall_left"]
    assert rope_subs[0][2].brightness == 10
    # All submissions should be priority 1 (mode)
    assert all(p == 1 for _, _, _, p in mx.submissions)
```

Similarly update `tests/test_sleep.py` and `tests/test_dj.py` to use `FakeMixer` instead of `FakeZoneManager`. The pattern is the same — replace zone calls with mixer submission assertions.

- [ ] **Step 6: Run all tests**

Run: `cd /home/digitalghost/projects/aether && .venv/bin/pytest -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
cd /home/digitalghost/projects/aether
git add src/aether/lighting/circadian.py src/aether/modes/focus.py src/aether/modes/sleep.py src/aether/modes/dj.py tests/test_focus.py tests/test_sleep.py tests/test_dj.py
git commit -m "refactor: migrate circadian engine and all modes to priority mixer"
```

---

### Task 4: Implement Gesture Detection

**Files:**
- Create: `src/aether/vision/gestures.py`
- Create: `tests/test_gestures.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_gestures.py`:

```python
import time
import pytest
from aether.vision.gestures import GestureClassifier, Gesture
from aether.config import GestureConfig


def make_classifier(consecutive=2, fist_frames=4, cooldown=1):
    cfg = GestureConfig(
        consecutive_frames=consecutive,
        fist_hold_frames=fist_frames,
        cooldown_sec=cooldown,
        feedback_flash=False,
    )
    return GestureClassifier(cfg)


def _thumbs_up_landmarks():
    """Fake 21-point hand landmarks: thumb up, fingers curled."""
    landmarks = [(0.5, 0.5)] * 21
    # Thumb tip (4) above thumb MCP (2)
    landmarks[4] = (0.5, 0.3)   # y=0.3 is higher (image coords, lower y = higher)
    landmarks[2] = (0.5, 0.5)
    # All other fingertips below their PIPs (curled)
    # Index: tip=8, pip=6
    landmarks[8] = (0.4, 0.7)
    landmarks[6] = (0.4, 0.5)
    # Middle: tip=12, pip=10
    landmarks[12] = (0.45, 0.7)
    landmarks[10] = (0.45, 0.5)
    # Ring: tip=16, pip=14
    landmarks[16] = (0.5, 0.7)
    landmarks[14] = (0.5, 0.5)
    # Pinky: tip=20, pip=18
    landmarks[20] = (0.55, 0.7)
    landmarks[18] = (0.55, 0.5)
    return landmarks


def _thumbs_down_landmarks():
    """Fake landmarks: thumb down, fingers curled."""
    landmarks = list(_thumbs_up_landmarks())
    # Thumb tip below thumb MCP
    landmarks[4] = (0.5, 0.7)
    landmarks[2] = (0.5, 0.5)
    return landmarks


def _fist_landmarks():
    """Fake landmarks: all fingers curled (fist)."""
    landmarks = [(0.5, 0.5)] * 21
    # All fingertips below their PIPs
    for tip, pip in [(4, 2), (8, 6), (12, 10), (16, 14), (20, 18)]:
        landmarks[tip] = (0.5, 0.7)
        landmarks[pip] = (0.5, 0.5)
    return landmarks


def _open_hand_landmarks():
    """Fake landmarks: all fingers extended (no gesture)."""
    landmarks = [(0.5, 0.5)] * 21
    for tip, pip in [(4, 2), (8, 6), (12, 10), (16, 14), (20, 18)]:
        landmarks[tip] = (0.5, 0.3)
        landmarks[pip] = (0.5, 0.5)
    return landmarks


def test_classify_thumbs_up():
    gc = make_classifier()
    result = gc._classify_landmarks(_thumbs_up_landmarks())
    assert result == Gesture.THUMBS_UP


def test_classify_thumbs_down():
    gc = make_classifier()
    result = gc._classify_landmarks(_thumbs_down_landmarks())
    assert result == Gesture.THUMBS_DOWN


def test_classify_fist():
    gc = make_classifier()
    result = gc._classify_landmarks(_fist_landmarks())
    assert result == Gesture.FIST


def test_classify_open_hand_is_none():
    gc = make_classifier()
    result = gc._classify_landmarks(_open_hand_landmarks())
    assert result is None


def test_debounce_requires_consecutive_frames():
    gc = make_classifier(consecutive=3)
    # 2 frames: not enough
    assert gc.update(_thumbs_up_landmarks()) is None
    assert gc.update(_thumbs_up_landmarks()) is None
    # 3rd frame: fires
    assert gc.update(_thumbs_up_landmarks()) == Gesture.THUMBS_UP


def test_cooldown_prevents_repeated_fire():
    gc = make_classifier(consecutive=1, cooldown=10)
    assert gc.update(_thumbs_up_landmarks()) == Gesture.THUMBS_UP
    # Immediate retry blocked by cooldown
    assert gc.update(_thumbs_up_landmarks()) is None


def test_fist_hold_requires_more_frames():
    gc = make_classifier(consecutive=2, fist_frames=4)
    assert gc.update(_fist_landmarks()) is None
    assert gc.update(_fist_landmarks()) is None
    assert gc.update(_fist_landmarks()) is None
    assert gc.update(_fist_landmarks()) == Gesture.FIST


def test_interrupted_gesture_resets():
    gc = make_classifier(consecutive=3)
    gc.update(_thumbs_up_landmarks())
    gc.update(_thumbs_up_landmarks())
    gc.update(_open_hand_landmarks())  # interrupted
    gc.update(_thumbs_up_landmarks())  # restart
    assert gc.update(_thumbs_up_landmarks()) is None  # only 2 consecutive
    assert gc.update(_thumbs_up_landmarks()) == Gesture.THUMBS_UP  # 3rd
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/digitalghost/projects/aether && .venv/bin/pytest tests/test_gestures.py -v`
Expected: FAIL — `cannot import GestureClassifier`

- [ ] **Step 3: Implement GestureClassifier**

Create `src/aether/vision/gestures.py`:

```python
from __future__ import annotations

import time
from enum import Enum

from aether.config import GestureConfig


class Gesture(Enum):
    THUMBS_UP = "thumbs_up"
    THUMBS_DOWN = "thumbs_down"
    FIST = "fist"


# MediaPipe hand landmark indices
THUMB_TIP = 4
THUMB_MCP = 2
INDEX_TIP = 8
INDEX_PIP = 6
MIDDLE_TIP = 12
MIDDLE_PIP = 10
RING_TIP = 16
RING_PIP = 14
PINKY_TIP = 20
PINKY_PIP = 18

FINGER_TIPS_AND_PIPS = [
    (INDEX_TIP, INDEX_PIP),
    (MIDDLE_TIP, MIDDLE_PIP),
    (RING_TIP, RING_PIP),
    (PINKY_TIP, PINKY_PIP),
]


class GestureClassifier:
    def __init__(self, config: GestureConfig):
        self._config = config
        self._consecutive_gesture: Gesture | None = None
        self._consecutive_count: int = 0
        self._cooldowns: dict[Gesture, float] = {}

    def _classify_landmarks(self, landmarks: list[tuple[float, float]]) -> Gesture | None:
        """Classify hand landmarks into a gesture. landmarks[i] = (x, y)."""
        thumb_tip_y = landmarks[THUMB_TIP][1]
        thumb_mcp_y = landmarks[THUMB_MCP][1]

        # Check if all four fingers are curled (tips below PIPs in image coords)
        fingers_curled = all(
            landmarks[tip][1] > landmarks[pip][1]
            for tip, pip in FINGER_TIPS_AND_PIPS
        )

        if not fingers_curled:
            # Check if ALL five digits are curled (including thumb) for fist
            thumb_curled = thumb_tip_y > thumb_mcp_y
            if thumb_curled and all(
                landmarks[tip][1] > landmarks[pip][1]
                for tip, pip in FINGER_TIPS_AND_PIPS
            ):
                return Gesture.FIST
            return None

        # Fingers curled — check thumb direction
        thumb_up = thumb_tip_y < thumb_mcp_y
        thumb_down = thumb_tip_y > thumb_mcp_y

        if thumb_up:
            return Gesture.THUMBS_UP
        elif thumb_down:
            # Thumb is also curled + all fingers curled = fist
            return Gesture.FIST
        return None

    def update(self, landmarks: list[tuple[float, float]]) -> Gesture | None:
        """Process one frame's hand landmarks. Returns a Gesture if one should fire."""
        gesture = self._classify_landmarks(landmarks)

        if gesture != self._consecutive_gesture:
            self._consecutive_gesture = gesture
            self._consecutive_count = 1 if gesture is not None else 0
            return None

        if gesture is None:
            return None

        self._consecutive_count += 1

        # Check frame threshold
        required = self._config.fist_hold_frames if gesture == Gesture.FIST else self._config.consecutive_frames
        if self._consecutive_count < required:
            return None

        # Check cooldown
        now = time.monotonic()
        last = self._cooldowns.get(gesture, 0)
        if now - last < self._config.cooldown_sec:
            return None

        # Fire!
        self._cooldowns[gesture] = now
        self._consecutive_count = 0
        return gesture
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/digitalghost/projects/aether && .venv/bin/pytest tests/test_gestures.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
cd /home/digitalghost/projects/aether
git add src/aether/vision/gestures.py tests/test_gestures.py
git commit -m "feat: implement hand gesture detection with debounce and cooldown"
```

---

### Task 5: Implement Vox Intent Classifier

**Files:**
- Create: `src/aether/vox/__init__.py`
- Create: `src/aether/vox/intent.py`
- Create: `tests/test_intent.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_intent.py`:

```python
from aether.vox.intent import classify_intent, Intent


def test_exact_keyword_focus():
    assert classify_intent("focus") == Intent.MODE_FOCUS


def test_exact_keyword_party():
    assert classify_intent("party") == Intent.MODE_PARTY


def test_exact_keyword_sleep():
    assert classify_intent("sleep") == Intent.MODE_SLEEP


def test_keyword_goodnight():
    assert classify_intent("goodnight") == Intent.MODE_SLEEP


def test_stop_focus():
    assert classify_intent("stop focus") == Intent.MODE_FOCUS_STOP


def test_end_focus():
    assert classify_intent("end focus") == Intent.MODE_FOCUS_STOP


def test_stop_party():
    assert classify_intent("stop party") == Intent.MODE_PARTY_STOP


def test_generic_stop():
    assert classify_intent("stop") == Intent.MODE_STOP


def test_generic_cancel():
    assert classify_intent("cancel") == Intent.MODE_STOP


def test_pause():
    assert classify_intent("pause") == Intent.PAUSE


def test_resume():
    assert classify_intent("resume") == Intent.RESUME


def test_unpause():
    assert classify_intent("unpause") == Intent.RESUME


def test_brighter():
    assert classify_intent("brighter") == Intent.BRIGHTNESS_UP


def test_dimmer():
    assert classify_intent("dimmer") == Intent.BRIGHTNESS_DOWN


def test_warmer():
    assert classify_intent("warmer") == Intent.COLOR_WARMER


def test_cooler():
    assert classify_intent("cooler") == Intent.COLOR_COOLER


def test_lights_off():
    assert classify_intent("lights off") == Intent.LIGHTS_OFF


def test_lights_on():
    assert classify_intent("lights on") == Intent.LIGHTS_ON


def test_case_insensitive():
    assert classify_intent("BRIGHTER") == Intent.BRIGHTNESS_UP


def test_substring_match():
    assert classify_intent("can you make it brighter") == Intent.BRIGHTNESS_UP


def test_multiword_before_single():
    assert classify_intent("stop focus") == Intent.MODE_FOCUS_STOP  # not MODE_STOP


def test_unknown_returns_none():
    assert classify_intent("what time is it") is None


def test_party_mode_synonym():
    assert classify_intent("party mode") == Intent.MODE_PARTY
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/digitalghost/projects/aether && .venv/bin/pytest tests/test_intent.py -v`
Expected: FAIL — `cannot import classify_intent`

- [ ] **Step 3: Implement intent classifier**

Create `src/aether/vox/__init__.py`:

```python
```

Create `src/aether/vox/intent.py`:

```python
from __future__ import annotations

from enum import Enum


class Intent(Enum):
    MODE_FOCUS = "mode_focus"
    MODE_FOCUS_STOP = "mode_focus_stop"
    MODE_PARTY = "mode_party"
    MODE_PARTY_STOP = "mode_party_stop"
    MODE_SLEEP = "mode_sleep"
    MODE_STOP = "mode_stop"
    PAUSE = "pause"
    RESUME = "resume"
    BRIGHTNESS_UP = "brightness_up"
    BRIGHTNESS_DOWN = "brightness_down"
    COLOR_WARMER = "color_warmer"
    COLOR_COOLER = "color_cooler"
    LIGHTS_OFF = "lights_off"
    LIGHTS_ON = "lights_on"


# Ordered: multi-word phrases first, then single words
KEYWORD_TABLE: list[tuple[str, Intent]] = [
    ("stop focus", Intent.MODE_FOCUS_STOP),
    ("end focus", Intent.MODE_FOCUS_STOP),
    ("stop party", Intent.MODE_PARTY_STOP),
    ("party mode", Intent.MODE_PARTY),
    ("lights off", Intent.LIGHTS_OFF),
    ("lights on", Intent.LIGHTS_ON),
    ("goodnight", Intent.MODE_SLEEP),
    ("unpause", Intent.RESUME),
    ("brighter", Intent.BRIGHTNESS_UP),
    ("bright", Intent.BRIGHTNESS_UP),
    ("dimmer", Intent.BRIGHTNESS_DOWN),
    ("dim", Intent.BRIGHTNESS_DOWN),
    ("warmer", Intent.COLOR_WARMER),
    ("cooler", Intent.COLOR_COOLER),
    ("focus", Intent.MODE_FOCUS),
    ("party", Intent.MODE_PARTY),
    ("sleep", Intent.MODE_SLEEP),
    ("stop", Intent.MODE_STOP),
    ("cancel", Intent.MODE_STOP),
    ("pause", Intent.PAUSE),
    ("resume", Intent.RESUME),
]


def classify_intent(text: str) -> Intent | None:
    """Classify transcribed text into an intent via keyword matching.

    Returns None if no keyword matches (caller should try Ollama fallback).
    """
    lower = text.lower().strip()
    for keyword, intent in KEYWORD_TABLE:
        if keyword in lower:
            return intent
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/digitalghost/projects/aether && .venv/bin/pytest tests/test_intent.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
cd /home/digitalghost/projects/aether
git add src/aether/vox/__init__.py src/aether/vox/intent.py tests/test_intent.py
git commit -m "feat: implement keyword-based voice intent classifier"
```

---

### Task 6: Implement Vox Mic Capture and Wake Word Detection

**Files:**
- Create: `src/aether/vox/mic.py`
- Create: `src/aether/vox/wake.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Add dependencies to pyproject.toml**

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
    "faster-whisper",
    "openwakeword",
]
```

- [ ] **Step 2: Install dependencies**

Run: `cd /home/digitalghost/projects/aether && .venv/bin/pip install faster-whisper openwakeword`

- [ ] **Step 3: Implement mic capture**

Create `src/aether/vox/mic.py`:

```python
from __future__ import annotations

import asyncio
import subprocess
import sys

import numpy as np


SAMPLE_RATE = 16000  # 16kHz for speech models
CHUNK_DURATION = 0.5  # 500ms chunks for wake word detection
CHUNK_SAMPLES = int(SAMPLE_RATE * CHUNK_DURATION)


class MicCapture:
    """Captures audio from a PipeWire source via pw-cat subprocess."""

    def __init__(self, source: str):
        self._source = source
        self._proc: subprocess.Popen | None = None

    async def start(self) -> bool:
        try:
            self._proc = subprocess.Popen(
                [
                    "pw-cat", "--record",
                    "--target", self._source,
                    "--format", "f32",
                    "--rate", str(SAMPLE_RATE),
                    "--channels", "1",
                    "-",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            print(f"[aether] VOX: mic capture started ({self._source})", file=sys.stderr)
            return True
        except FileNotFoundError:
            print("[aether] VOX: pw-cat not found", file=sys.stderr)
            return False
        except Exception as e:
            print(f"[aether] VOX: mic capture failed: {e}", file=sys.stderr)
            return False

    async def read_chunk(self) -> np.ndarray | None:
        """Read one audio chunk. Returns None if stream ended."""
        if self._proc is None or self._proc.stdout is None:
            return None
        raw = await asyncio.to_thread(
            self._proc.stdout.read, CHUNK_SAMPLES * 4  # float32 = 4 bytes
        )
        if not raw:
            return None
        samples = np.frombuffer(raw, dtype=np.float32)
        # Filter NaN/Inf (PipeWire can produce garbage in first chunk)
        clean = samples[np.isfinite(samples)]
        return clean if len(clean) > 0 else None

    async def read_seconds(self, seconds: float, silence_timeout: float = 1.5) -> np.ndarray:
        """Record for up to `seconds`, stopping early on silence."""
        chunks = []
        total_samples = int(SAMPLE_RATE * seconds)
        collected = 0
        silence_samples = 0
        silence_limit = int(SAMPLE_RATE * silence_timeout)

        while collected < total_samples:
            chunk = await self.read_chunk()
            if chunk is None:
                break
            chunks.append(chunk)
            collected += len(chunk)

            # Detect silence
            energy = float(np.sqrt(np.mean(chunk ** 2)))
            if energy < 0.005:
                silence_samples += len(chunk)
                if silence_samples >= silence_limit:
                    break
            else:
                silence_samples = 0

        return np.concatenate(chunks) if chunks else np.array([], dtype=np.float32)

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            self._proc.wait()
        self._proc = None
```

- [ ] **Step 4: Implement wake word detector**

Create `src/aether/vox/wake.py`:

```python
from __future__ import annotations

import sys

import numpy as np


class WakeWordDetector:
    """Wraps openWakeWord for 'Aether' wake word detection."""

    def __init__(self, wake_word: str = "aether"):
        self._wake_word = wake_word
        self._model = None
        self._threshold = 0.5

    def load(self) -> bool:
        try:
            from openwakeword.model import Model
            self._model = Model(
                wakeword_models=[self._wake_word],
                inference_framework="onnx",
            )
            print(f"[aether] VOX: wake word model loaded ({self._wake_word})", file=sys.stderr)
            return True
        except Exception as e:
            print(f"[aether] VOX: wake word model failed to load: {e}", file=sys.stderr)
            return False

    def detect(self, audio_chunk: np.ndarray) -> bool:
        """Feed an audio chunk (16kHz float32). Returns True if wake word detected."""
        if self._model is None:
            return False

        # openwakeword expects int16 samples
        int16_audio = (audio_chunk * 32767).astype(np.int16)
        prediction = self._model.predict(int16_audio)

        for key, score in prediction.items():
            if score >= self._threshold:
                self._model.reset()
                return True
        return False
```

- [ ] **Step 5: Commit**

```bash
cd /home/digitalghost/projects/aether
git add pyproject.toml src/aether/vox/mic.py src/aether/vox/wake.py
git commit -m "feat: implement mic capture and wake word detection for Vox"
```

---

### Task 7: Implement Vox STT and Handler

**Files:**
- Create: `src/aether/vox/stt.py`
- Create: `src/aether/vox/handler.py`

- [ ] **Step 1: Implement STT wrapper**

Create `src/aether/vox/stt.py`:

```python
from __future__ import annotations

import sys

import numpy as np


class SpeechToText:
    """Wraps faster-whisper for on-demand speech-to-text."""

    def __init__(self, model_size: str = "small"):
        self._model_size = model_size
        self._model = None

    def _ensure_model(self) -> bool:
        if self._model is not None:
            return True
        try:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(self._model_size, device="cuda", compute_type="float16")
            print(f"[aether] VOX: whisper model loaded ({self._model_size})", file=sys.stderr)
            return True
        except Exception as e:
            print(f"[aether] VOX: whisper model failed: {e}", file=sys.stderr)
            return False

    def transcribe(self, audio: np.ndarray, sr: int = 16000) -> str | None:
        """Transcribe audio to text. Returns None on failure."""
        if not self._ensure_model():
            return None
        try:
            segments, _ = self._model.transcribe(audio, language="en")
            text = " ".join(seg.text.strip() for seg in segments).strip()
            return text if text else None
        except Exception as e:
            print(f"[aether] VOX: transcription failed: {e}", file=sys.stderr)
            return None
```

- [ ] **Step 2: Implement handler**

Create `src/aether/vox/handler.py`:

```python
from __future__ import annotations

import sys
from datetime import datetime, timezone

from aether.lighting.ramp import ColorState
from aether.state import Event, State, StateMachine
from aether.vox.intent import Intent


class VoxHandler:
    """Executes voice command intents."""

    def __init__(self, state_machine: StateMachine, mixer, mqtt, config):
        self._sm = state_machine
        self._mixer = mixer
        self._mqtt = mqtt
        self._config = config

    def execute(self, intent: Intent, text: str) -> None:
        print(f"[aether] VOX: intent={intent.value} text={text!r}", file=sys.stderr)

        # Publish to MQTT
        self._mqtt.publish("aether/vox/last_command", {
            "text": text,
            "intent": intent.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, retain=True)

        # Mode transitions
        if intent == Intent.MODE_FOCUS and self._sm.state == State.PRESENT:
            self._sm.handle_event(Event.FOCUS_START)
        elif intent == Intent.MODE_FOCUS_STOP and self._sm.state == State.FOCUS:
            self._sm.handle_event(Event.FOCUS_STOP)
        elif intent == Intent.MODE_PARTY and self._sm.state == State.PRESENT:
            self._sm.handle_event(Event.PARTY_START)
        elif intent == Intent.MODE_PARTY_STOP and self._sm.state == State.PARTY:
            self._sm.handle_event(Event.PARTY_STOP)
        elif intent == Intent.MODE_SLEEP and self._sm.state == State.PRESENT:
            self._sm.handle_event(Event.SLEEP_START)
        elif intent == Intent.MODE_STOP:
            self._stop_current_mode()
        elif intent == Intent.PAUSE:
            self._pause()
        elif intent == Intent.RESUME:
            self._resume()
        elif intent == Intent.BRIGHTNESS_UP:
            self._adjust_brightness(20)
        elif intent == Intent.BRIGHTNESS_DOWN:
            self._adjust_brightness(-20)
        elif intent == Intent.COLOR_WARMER:
            self._shift_color_temp(warm=True)
        elif intent == Intent.COLOR_COOLER:
            self._shift_color_temp(warm=False)
        elif intent == Intent.LIGHTS_OFF:
            off = ColorState(r=0, g=0, b=0, brightness=0)
            ttl = self._config.mixer.manual_ttl_sec
            self._mixer.submit_all("voice", off, priority=0, ttl_sec=ttl)
            self._mixer.resolve()
        elif intent == Intent.LIGHTS_ON:
            self._mixer.release_all("voice")
            self._mixer.resolve()

    def _stop_current_mode(self) -> None:
        if self._sm.state == State.FOCUS:
            self._sm.handle_event(Event.FOCUS_STOP)
        elif self._sm.state == State.PARTY:
            self._sm.handle_event(Event.PARTY_STOP)
        elif self._sm.state == State.SLEEP:
            self._sm.handle_event(Event.SLEEP_CANCEL)

    def _pause(self) -> None:
        from aether.lighting.zones import ZoneManager
        # This is called from the event loop via the vox pipeline
        # The actual pause logic is in the daemon — publish MQTT command
        self._mqtt.publish(f"{self._config.mqtt.topic_prefix}/control", "pause")

    def _resume(self) -> None:
        self._mqtt.publish(f"{self._config.mqtt.topic_prefix}/control", "resume")

    def _adjust_brightness(self, delta: int) -> None:
        ttl = self._config.mixer.manual_ttl_sec
        claims = self._mixer.get_active_claims()
        for zone, claim in claims.items():
            current_br = claim.color.brightness
            new_br = max(0, min(100, current_br + delta))
            new_color = ColorState(
                r=claim.color.r, g=claim.color.g, b=claim.color.b,
                brightness=new_br,
            )
            self._mixer.submit("voice", zone, new_color, priority=0, ttl_sec=ttl)
        self._mixer.resolve()

    def _shift_color_temp(self, warm: bool) -> None:
        ttl = self._config.mixer.manual_ttl_sec
        claims = self._mixer.get_active_claims()
        for zone, claim in claims.items():
            r, g, b = claim.color.r, claim.color.g, claim.color.b
            if warm:
                r = min(255, r + 30)
                b = max(0, b - 30)
            else:
                r = max(0, r - 30)
                b = min(255, b + 30)
            new_color = ColorState(r=r, g=g, b=b, brightness=claim.color.brightness)
            self._mixer.submit("voice", zone, new_color, priority=0, ttl_sec=ttl)
        self._mixer.resolve()
```

- [ ] **Step 3: Commit**

```bash
cd /home/digitalghost/projects/aether
git add src/aether/vox/stt.py src/aether/vox/handler.py
git commit -m "feat: implement Vox STT wrapper and intent action handler"
```

---

### Task 8: Wire Everything into the Daemon

**Files:**
- Modify: `src/aether/cli.py`
- Modify: `src/aether/vision/presence.py`

This is the integration task — wiring mixer, vox pipeline, and gestures into the daemon.

- [ ] **Step 1: Update cli.py**

Key changes to `_run_daemon()`:

1. Create `Mixer` and pass it to `CircadianEngine` (instead of `ZoneManager`)
2. Pass mixer to mode constructors (instead of zones)
3. Start mixer's `run()` coroutine in `asyncio.gather`
4. If `config.vox.enabled`, start the vox pipeline coroutine
5. If `config.gestures.enabled`, create `GestureClassifier` and integrate into `process_frame`
6. Add `vox-test` CLI command

The full daemon rewire:

```python
async def _run_daemon(config):
    loop = asyncio.get_running_loop()
    mqtt = MqttClient(broker=config.mqtt.broker, port=config.mqtt.port)
    adapter = GoveeAdapter(mqtt, config.zones, topic_prefix=config.mqtt.topic_prefix)
    zones = ZoneManager(adapter)
    mixer = Mixer(zones)
    state_machine = StateMachine()
    circadian = CircadianEngine(config, mixer)
    presence = PresenceDetector(config.presence, state_machine)
    camera = Camera(config.presence.camera_index, config.presence.frame_interval_ms)
    sentry = SentryAlert(
        adapter=adapter,
        floor_zone_name="floor",
        flash_color=config.alerts.sentry.floor_flash_color,
        flash_count=config.alerts.sentry.floor_flash_count,
    )

    # Gesture classifier
    gesture_classifier = None
    if config.gestures.enabled:
        from aether.vision.gestures import GestureClassifier, Gesture
        gesture_classifier = GestureClassifier(config.gestures)

    alert_task = None
    active_mode_task = None
    mode_cancel = asyncio.Event()
    mode_pause = asyncio.Event()

    # ... _stop_active_mode and _start_mode unchanged ...

    def handle_transition(t: Transition):
        nonlocal alert_task
        print(f"[aether] {t.from_state.value} → {t.to_state.value} ({t.reason})", file=sys.stderr)
        adapter.publish_state(t.to_state.value)
        adapter.publish_transition(t.from_state.value, t.to_state.value, t.reason)
        circadian.on_state_change(t.to_state)

        if t.to_state == State.PRESENT and t.from_state == State.AWAY:
            if alert_task and not alert_task.done():
                alert_task.cancel()
            asyncio.ensure_future(circadian.run_return_ramp())

        if t.to_state == State.PRESENT and t.from_state in (State.FOCUS, State.PARTY, State.SLEEP):
            _stop_active_mode()
            asyncio.ensure_future(circadian.run_return_ramp())

        if t.to_state == State.FOCUS:
            focus = FocusMode(config.focus, mixer, mode_cancel, mode_pause)
            _start_mode(focus.run())
        elif t.to_state == State.PARTY:
            party = DJMode(config.party, mixer, mqtt, mode_cancel, mode_pause)
            _start_mode(party.run())
        elif t.to_state == State.SLEEP:
            sleep = SleepMode(config.sleep, mixer, mqtt, mode_cancel, mode_pause)
            _start_mode(sleep.run())
        elif t.to_state == State.AWAY and t.from_state == State.SLEEP:
            _stop_active_mode()

    state_machine._on_transition = handle_transition

    # ... MQTT command handler unchanged ...
    # ... presence MQTT wrapper unchanged ...

    # Build coroutine list
    coros = [
        camera.run(presence.process_frame),
        circadian.run(),
        mqtt.run(),
        mixer.run(tick_interval=config.mixer.tick_interval_sec),
    ]

    # Vox pipeline
    if config.vox.enabled:
        from aether.vox.mic import MicCapture
        from aether.vox.wake import WakeWordDetector
        from aether.vox.stt import SpeechToText
        from aether.vox.intent import classify_intent
        from aether.vox.handler import VoxHandler

        async def _vox_pipeline():
            mic = MicCapture(config.vox.mic_source)
            if not await mic.start():
                return

            wake = WakeWordDetector(config.vox.wake_word)
            if not wake.load():
                mic.stop()
                return

            stt = SpeechToText(config.vox.whisper_model)
            handler = VoxHandler(state_machine, mixer, mqtt, config)

            print("[aether] VOX: pipeline ready", file=sys.stderr)

            try:
                while True:
                    chunk = await mic.read_chunk()
                    if chunk is None:
                        break

                    if wake.detect(chunk):
                        print("[aether] VOX: wake word detected", file=sys.stderr)

                        # Feedback flash
                        if config.vox.feedback_flash:
                            flash = ColorState(r=255, g=255, b=255, brightness=100)
                            mixer.submit("feedback", "floor", flash, priority=0, ttl_sec=1)
                            mixer.resolve()

                        # Record command
                        audio = await mic.read_seconds(
                            config.vox.command_timeout_sec,
                            silence_timeout=config.vox.silence_timeout_sec,
                        )
                        if len(audio) == 0:
                            continue

                        # Transcribe
                        text = await asyncio.to_thread(stt.transcribe, audio)
                        if text is None:
                            continue

                        print(f"[aether] VOX: heard: {text!r}", file=sys.stderr)

                        # Classify
                        intent = classify_intent(text)
                        if intent is None:
                            print(f"[aether] VOX: no keyword match for {text!r}, skipping", file=sys.stderr)
                            continue

                        handler.execute(intent, text)
            finally:
                mic.stop()

        coros.append(_vox_pipeline())

    print("[aether] Daemon running. Press Ctrl+C to stop.", file=sys.stderr)

    try:
        await asyncio.gather(*coros)
    except KeyboardInterrupt:
        print("\n[aether] Shutting down...", file=sys.stderr)
    finally:
        _stop_active_mode()
        camera.release()
        mqtt.disconnect()
```

- [ ] **Step 2: Integrate gesture detection into presence.py**

In `src/aether/vision/presence.py`, update `PresenceDetector` to optionally run hand detection:

```python
class PresenceDetector:
    """Runs MediaPipe pose on frames and feeds PresenceTracker."""

    def __init__(self, presence_config, state_machine: StateMachine, gesture_callback=None):
        self._tracker = PresenceTracker(
            absence_timeout_sec=presence_config.absence_timeout_sec,
            state_machine=state_machine,
        )
        options = vision.PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=POSE_MODEL_PATH),
            running_mode=vision.RunningMode.IMAGE,
            min_pose_detection_confidence=presence_config.detection_confidence,
        )
        self._landmarker = vision.PoseLandmarker.create_from_options(options)
        self._gesture_callback = gesture_callback
        self._hand_landmarker = None

        if gesture_callback is not None:
            hand_model_path = str(
                __import__("pathlib").Path.home() / ".cache" / "aether" / "hand_landmarker.task"
            )
            try:
                hand_options = vision.HandLandmarkerOptions(
                    base_options=BaseOptions(model_asset_path=hand_model_path),
                    running_mode=vision.RunningMode.IMAGE,
                    min_hand_detection_confidence=0.5,
                    num_hands=1,
                )
                self._hand_landmarker = vision.HandLandmarker.create_from_options(hand_options)
                print("[aether] Gesture: hand landmarker loaded", file=sys.stderr)
            except Exception as e:
                print(f"[aether] Gesture: hand landmarker failed: {e}", file=sys.stderr)

    def process_frame(self, frame: np.ndarray) -> None:
        rgb = frame[:, :, ::-1]  # BGR -> RGB
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb.copy())
        result = self._landmarker.detect(mp_image)
        human_detected = len(result.pose_landmarks) > 0
        self._tracker.update(human_detected)

        # Hand gesture detection
        if self._hand_landmarker is not None and self._gesture_callback is not None:
            try:
                hand_result = self._hand_landmarker.detect(mp_image)
                if hand_result.hand_landmarks:
                    # Convert to (x, y) tuples
                    landmarks = [
                        (lm.x, lm.y) for lm in hand_result.hand_landmarks[0]
                    ]
                    self._gesture_callback(landmarks)
            except Exception:
                pass  # Don't let gesture errors break presence detection

    @property
    def tracker(self) -> PresenceTracker:
        return self._tracker
```

In `_run_daemon`, pass the gesture callback when creating PresenceDetector:

```python
    # Gesture handling callback
    def _on_gesture_landmarks(landmarks):
        if gesture_classifier is None:
            return
        gesture = gesture_classifier.update(landmarks)
        if gesture is None:
            return
        print(f"[aether] Gesture: {gesture.value}", file=sys.stderr)

        # Feedback flash
        if config.gestures.feedback_flash:
            flash = ColorState(r=255, g=255, b=255, brightness=100)
            mixer.submit("feedback", "floor", flash, priority=0, ttl_sec=1)
            mixer.resolve()

        # Execute
        from aether.vox.intent import Intent
        if gesture == Gesture.THUMBS_UP:
            handler.execute(Intent.BRIGHTNESS_UP, "gesture:thumbs_up")
        elif gesture == Gesture.THUMBS_DOWN:
            handler.execute(Intent.BRIGHTNESS_DOWN, "gesture:thumbs_down")
        elif gesture == Gesture.FIST:
            # Toggle pause/resume
            if zones.paused:
                loop.call_soon_threadsafe(
                    _handle_mqtt_command_inner,
                    f"{config.mqtt.topic_prefix}/control", "resume"
                )
            else:
                loop.call_soon_threadsafe(
                    _handle_mqtt_command_inner,
                    f"{config.mqtt.topic_prefix}/control", "pause"
                )

        # Publish gesture MQTT
        from datetime import datetime, timezone
        mqtt.publish("aether/gesture/last", {
            "gesture": gesture.value,
            "action": gesture.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, retain=True)

    gesture_cb = _on_gesture_landmarks if gesture_classifier else None
    presence = PresenceDetector(config.presence, state_machine, gesture_callback=gesture_cb)
```

- [ ] **Step 3: Add vox-test CLI command**

Add to cli.py after the existing commands:

```python
@cli.command("vox-test")
@click.option("--config", "config_path", type=click.Path(), default=None)
def vox_test(config_path):
    """Test the voice pipeline — prints wake word detections and transcriptions."""
    from pathlib import Path

    config = load_config(Path(config_path) if config_path else None)
    asyncio.run(_vox_test(config))


async def _vox_test(config):
    from aether.vox.mic import MicCapture
    from aether.vox.wake import WakeWordDetector
    from aether.vox.stt import SpeechToText
    from aether.vox.intent import classify_intent

    mic = MicCapture(config.vox.mic_source)
    if not await mic.start():
        return

    wake = WakeWordDetector(config.vox.wake_word)
    if not wake.load():
        mic.stop()
        return

    stt = SpeechToText(config.vox.whisper_model)

    print("Listening for wake word... (Ctrl+C to stop)")
    try:
        while True:
            chunk = await mic.read_chunk()
            if chunk is None:
                break
            if wake.detect(chunk):
                print(">>> Wake word detected! Recording command...")
                audio = await mic.read_seconds(
                    config.vox.command_timeout_sec,
                    silence_timeout=config.vox.silence_timeout_sec,
                )
                if len(audio) == 0:
                    print(">>> No audio captured")
                    continue
                text = await asyncio.to_thread(stt.transcribe, audio)
                if text:
                    intent = classify_intent(text)
                    print(f">>> Heard: {text!r} → Intent: {intent}")
                else:
                    print(">>> Transcription failed")
    except KeyboardInterrupt:
        pass
    finally:
        mic.stop()
```

- [ ] **Step 4: Run all tests**

Run: `cd /home/digitalghost/projects/aether && .venv/bin/pytest -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
cd /home/digitalghost/projects/aether
git add src/aether/cli.py src/aether/vision/presence.py
git commit -m "feat: wire mixer, vox pipeline, and gestures into daemon"
```

---

### Task 9: Update CLAUDE.md and Run Full Test Suite

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update CLAUDE.md**

Add to the Tech Stack section:
```
- **faster-whisper** — speech-to-text for voice commands
- **openwakeword** — wake word detection ("Aether")
```

Add to the Commands section:
```bash
# Phase 3
python -m aether vox-test            # Test voice pipeline
```

Update Architecture:
```
Single Python async process: C920 → MediaPipe pose + hands → state machine (PRESENT/AWAY/FOCUS/PARTY/SLEEP) → priority mixer → circadian engine + mode coroutines → ZoneManager → GoveeAdapter → MQTT → govee2mqtt → Govee lights. Voice: UM02 mic → openWakeWord → faster-whisper → intent classifier → mixer/state machine.
```

Add to Design Specs:
```
- `docs/superpowers/specs/2026-03-28-aether-phase3-core-design.md` — Phase 3 Core (mixer/vox/gestures)
```

- [ ] **Step 2: Run full test suite**

Run: `cd /home/digitalghost/projects/aether && .venv/bin/pytest -v`
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
cd /home/digitalghost/projects/aether
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with Phase 3 architecture and commands"
```

---

## Task Dependency Order

```
Task 1 (config) ─────► Task 2 (mixer) ─────► Task 3 (refactor) ──┬──► Task 8 (daemon wiring) ──► Task 9 (docs)
                                                                    │
                                              Task 4 (gestures) ──┘
                                              Task 5 (intent) ────┘
                                              Task 6 (mic/wake) ──┘
                                              Task 7 (stt/handler)┘
```

Tasks 1 → 2 → 3 are sequential (each depends on the prior). After Task 3, Tasks 4, 5, 6, 7 can run in parallel. Task 8 depends on all of them. Task 9 is final.
