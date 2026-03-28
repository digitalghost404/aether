# Aether Phase 2 — FOCUS, PARTY, SLEEP: Design Spec

**Date:** 2026-03-27
**Status:** Approved — ready for implementation planning
**Repo:** ~/projects/aether
**Branch:** development
**Depends on:** Phase 1 MVP (complete, tagged v0.1.0)

---

## Overview

Phase 2 adds three new states to Aether's state machine: FOCUS (Pomodoro work sessions with locked lighting), PARTY (beat-synced DJ lightshow via PipeWire + librosa), and SLEEP (5-minute cascade shutdown). All three build on the existing state machine, ZoneManager, and MQTT infrastructure from Phase 1. A global pause/resume system is also added for suppressing all light output without stopping the daemon.

### Constraints

- **Platform API only** — Govee LAN API is blocked by Xfinity XB8 AP isolation. All device control goes through govee2mqtt's Platform API path: ~1-2s latency per device, ~10 req/sec rate limit.
- **No new hardware** — uses existing C920 webcam, PipeWire audio (already the system audio server), and 5 Govee lights.
- **Mutually exclusive states** — FOCUS, PARTY, and SLEEP cannot overlap. All enter from PRESENT, exit to PRESENT (or AWAY for SLEEP completion).

---

## State Machine Extensions

### New States

| State | Purpose |
|-------|---------|
| FOCUS | Pomodoro work session — locked cool white, rope progress bar |
| PARTY | DJ Lightshow — beat-synced lighting from PipeWire audio |
| SLEEP | Cascade shutdown — room "falls asleep" over 5 minutes |

### New Events

| Event | Triggers |
|-------|----------|
| FOCUS_START | CLI `aether focus` or MQTT `aether/mode/set` → `focus` |
| FOCUS_STOP | CLI `aether focus stop`, MQTT, or Pomodoro cycles complete |
| PARTY_START | CLI `aether party` or MQTT `aether/mode/set` → `party` |
| PARTY_STOP | CLI `aether party stop`, MQTT, or 2 min silence |
| SLEEP_START | CLI `aether sleep` or MQTT `aether/mode/set` → `sleep` |
| SLEEP_CANCEL | CLI `aether sleep stop` or MQTT |

### Transition Table (additions to Phase 1)

```
PRESENT → FOCUS       (FOCUS_START)
FOCUS → PRESENT       (FOCUS_STOP)
PRESENT → PARTY       (PARTY_START)
PARTY → PRESENT       (PARTY_STOP)
PRESENT → SLEEP       (SLEEP_START)
SLEEP → PRESENT       (SLEEP_CANCEL)
SLEEP → AWAY          (cascade complete — automatic)
```

### Transition Rules

- All three new states can only be entered from PRESENT. You must be in the room.
- No direct transitions between FOCUS/PARTY/SLEEP. Exit to PRESENT first.
- **Absence detection is suppressed in FOCUS and PARTY.** Camera keeps running but the absence timer does not trigger AWAY transitions. You're at the desk / in the room.
- **SLEEP completes to AWAY**, not PRESENT. Once the cascade finishes (all lights off), the daemon enters AWAY. Next morning when you walk in, the normal AWAY → PRESENT sunrise ramp fires. The room wakes up with you.
- SLEEP_CANCEL during the cascade snaps back to PRESENT and restores circadian lighting over 3 seconds.

---

## FOCUS Mode

### Module

`src/aether/modes/focus.py`

### Behavior

**Pomodoro timer** — classic 25/5 structure:
- 25 min work period
- 5 min short break
- 15 min long break every 4 cycles
- Default: 4 cycles (~2 hours), configurable via `--cycles N`
- `--cycles 0` for indefinite (runs until manually stopped)

**Lighting during work period:**
- Monitor backlight → locked cool white (`[255, 255, 255]`), 100% brightness
- Wall ropes (both) → warm dim at 10% brightness, ramping linearly to 100% over the 25-min work period (progress bar effect)
- Floor lamp → off
- Bedroom lamp → off

**Lighting during short break:**
- Ropes flash 2x (bright → dim → bright → dim), then drop to 10% at green-warm (`[180, 230, 180]`)
- Monitor dims to 60%
- Ropes at 10% reset = visual "cycle reset" before next work period

**Lighting during long break:**
- Same as short break but ropes go to relaxed amber at 70% brightness

**Break → work transition:**
- Ropes flash 2x, reset to 10% warm dim
- Monitor back to 100% cool white
- Next work cycle begins, rope ramp restarts from 10%

**Exit conditions:**
- `aether focus stop` (CLI or MQTT)
- All cycles complete (default 4)
- Returns to PRESENT, circadian resumes immediately

### MQTT Topics

| Topic | Payload | Retained |
|-------|---------|:--------:|
| `aether/focus/state` | `"work"` / `"short_break"` / `"long_break"` | Yes |
| `aether/focus/timer` | `{"remaining_sec": 1234, "cycle": 2, "total_cycles": 4}` | No |

Timer published every 30 seconds during active focus session.

---

## PARTY Mode (DJ Lightshow)

### Module

`src/aether/modes/dj.py`

### Audio Pipeline

1. Tap PipeWire default audio sink via subprocess: `pw-cat --record --target @DEFAULT_AUDIO_SINK@ --format f32 --rate 22050 --channels 1 -`
2. Read PCM chunks from stdout into numpy arrays
3. Feed to librosa for beat tracking and onset detection
4. Extract: BPM, beat positions, onset strength / energy envelope

### Lighting Strategy (Hybrid — Platform API safe)

**Base layer** (monitor, wall_left, wall_right, bedroom):
- Analyze audio energy over 4-8 beat windows
- Shift base color on phrase boundaries (every 8 beats at detected BPM)
- At 120 BPM = color change every ~4 seconds
- Colors cycle through the `party.palette` config list
- Smooth transitions between colors using existing ramp infrastructure

**Accent layer** (floor lamp):
- Pulses brightness on strong beats (onset detection from librosa)
- Brightness toggles between `accent_brightness_low` (40%) and `accent_brightness_high` (100%)
- At 120 BPM = ~2 beats/sec = ~2 API calls/sec for one device

### Rate Budget

| Source | Requests/sec |
|--------|-------------|
| Floor lamp accent | ~2 |
| Base color shifts (4 devices / ~4 sec each) | ~1 |
| **Total peak** | **~3** |
| **Limit** | **10** |

### No Music Handling

- If the audio tap produces silence for 2 minutes (`party.silence_timeout_sec`), PARTY exits to PRESENT automatically.
- If PipeWire is not available or `pw-cat` fails to start, PARTY refuses to enter and logs an error.

### Exit

- `aether party stop` (CLI or MQTT)
- 2 min silence timeout
- Ramps back to circadian over 3 seconds

### New Dependency

`librosa` — added to pyproject.toml. Actively maintained, pip-installs cleanly. Pulls in scipy/numpy (numpy already present via mediapipe).

---

## SLEEP Mode (Cascade Shutdown)

### Module

`src/aether/modes/sleep.py`

### Cascade Sequence (5 minutes total)

| Time | Device | Action |
|------|--------|--------|
| 0:00 | Monitor backlight | Fade to 0 over 30s |
| 0:30 | Wall ropes (both) | Fade from current → warm amber → off over 2 min |
| 2:30 | Floor lamp | Fade to warm nightlight (10%) over 1 min, then off |
| 3:30 | Bedroom lamp | Fade to deep orange (`[200, 100, 30]`) at 5% over 1.5 min |
| 5:00 | Bedroom lamp | Off. Transition to AWAY. |

The room falls asleep from the work area outward. Bedroom lamp is the last light alive.

### Rate Budget

Each fade uses the existing ramp infrastructure. One device fading = ~1 update every 10-15 seconds. Never more than 2 devices fading simultaneously = well under rate limit.

### Cancel

`aether sleep stop` at any point during cascade → snap to PRESENT, ramp to current circadian target over 3 seconds.

### Completion

When the cascade finishes, SLEEP transitions to AWAY automatically. Next morning when you walk in, the standard AWAY → PRESENT sunrise ramp fires.

### MQTT Topic

| Topic | Payload | Retained |
|-------|---------|:--------:|
| `aether/sleep/stage` | `"monitor"` / `"ropes"` / `"floor"` / `"bedroom"` / `"complete"` | Yes |

---

## Pause / Resume

### Purpose

Global pause for situations where Aether should be silent (video calls, screen recordings, etc.). The daemon keeps running — camera, state machine, timers all continue internally — but no commands are published to lights.

### Behavior

- `aether pause` — sets a `paused` flag. ZoneManager's `set_zone` no-ops when paused. No MQTT light commands published.
- `aether resume` — clears the flag. Snapshots current state and immediately applies correct lighting (circadian, focus ramp position, etc.).
- **Timers pause too.** Pomodoro work/break timers, sleep cascade timers, and party silence timeout all freeze while paused. You don't lose work time to a video call.

### MQTT

| Topic | Payload | Retained |
|-------|---------|:--------:|
| `aether/paused` | `true` / `false` | Yes |

### Implementation

A `paused` boolean on a coordinator object (or directly on ZoneManager). Timer coroutines check the flag in their sleep loops and skip elapsed time while paused.

---

## Configuration

### New Sections in `config.yaml`

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
  accent_zone: floor
  accent_brightness_low: 40
  accent_brightness_high: 100
  base_shift_beats: 8
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

### New Pydantic Models

- `FocusConfig` — work/break durations, cycles, colors
- `PartyConfig` — accent zone, brightness range, beat shift interval, silence timeout, palette
- `SleepConfig` — total duration, bedroom final color/brightness
- All added as optional fields on `AetherConfig` with defaults matching the YAML above

---

## CLI Commands

```
aether focus [--cycles N] [--work N] [--break N]
aether focus stop
aether party
aether party stop
aether sleep
aether sleep stop
aether pause
aether resume
aether status    # extended: shows mode, Pomodoro progress, sleep stage, paused state
```

All commands publish to MQTT. The daemon subscribes to `aether/mode/set` and `aether/control` topics to receive commands. CLI is an ergonomic layer over MQTT — any MQTT publisher (KDE shortcut scripts, Home Assistant, future voice commands) can trigger the same actions.

---

## MQTT Topic Contract (Phase 2 additions)

| Topic | Payload | Retained |
|-------|---------|:--------:|
| `aether/mode/set` | `"focus"` / `"party"` / `"sleep"` / `"focus_stop"` / `"party_stop"` / `"sleep_stop"` | No |
| `aether/control` | `"pause"` / `"resume"` | No |
| `aether/paused` | `true` / `false` | Yes |
| `aether/focus/state` | `"work"` / `"short_break"` / `"long_break"` | Yes |
| `aether/focus/timer` | `{"remaining_sec": N, "cycle": N, "total_cycles": N}` | No |
| `aether/sleep/stage` | `"monitor"` / `"ropes"` / `"floor"` / `"bedroom"` / `"complete"` | Yes |

---

## File Changes

### Modified

| File | Changes |
|------|---------|
| `state.py` | Add FOCUS, PARTY, SLEEP states; add 6 new events; extend transition table |
| `config.py` | Add FocusConfig, PartyConfig, SleepConfig models; add to AetherConfig |
| `cli.py` | Add focus, party, sleep, pause, resume commands; extend status output |
| `lighting/zones.py` | Add `paused` flag to `set_zone`; per-zone fading support for sleep cascade |
| `config.example.yaml` | Add focus/party/sleep sections with defaults |
| `pyproject.toml` | Add `librosa` dependency |

### New

| File | Purpose |
|------|---------|
| `src/aether/modes/__init__.py` | Modes package |
| `src/aether/modes/focus.py` | Pomodoro timer, work/break cycling, rope brightness ramp |
| `src/aether/modes/dj.py` | PipeWire subprocess, librosa beat/onset analysis, accent + base lighting |
| `src/aether/modes/sleep.py` | Cascade shutdown coroutine with staged timing |

### Integration

In `cli.py::_run_daemon`:
- `handle_transition` callback matches new states and spins up mode coroutines via `asyncio.ensure_future`
- Each mode coroutine receives ZoneManager, config, and an `asyncio.Event` for cancellation
- Pause/resume sets the flag on ZoneManager and publishes MQTT
- The daemon subscribes to `aether/mode/set` and `aether/control` for receiving commands from CLI/external publishers

---

## Testing

### New Test Files

| File | Coverage |
|------|----------|
| `test_focus.py` | Pomodoro timer cycling (work → short break → work → long break), brightness ramp math (10% → 100% over duration), cycle completion exit |
| `test_sleep.py` | Cascade stage timing (correct devices at correct times), cancel mid-cascade restores circadian, completion transitions to AWAY |
| `test_dj.py` | Beat detection with synthetic audio, rate budget assertions (never exceed 10 req/sec), silence timeout exit |

### Extended

| File | New Cases |
|------|-----------|
| `test_state.py` | All new transitions valid, invalid transitions rejected (e.g., AWAY → FOCUS), absence suppression in FOCUS/PARTY |

---

## Dependencies

### New

| Package | Purpose | Size Impact |
|---------|---------|-------------|
| `librosa` | Beat tracking, onset detection, BPM estimation | ~20MB + scipy (~30MB) |

### Existing (unchanged)

mediapipe, opencv-python-headless, paho-mqtt, pydantic, httpx, click

### External (no change)

mosquitto (system service), govee2mqtt (Docker container), PipeWire (system audio — already running)
