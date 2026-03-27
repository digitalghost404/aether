# Aether — The Living Room: Design Spec

**Date:** 2026-03-27
**Status:** Approved — ready for implementation planning
**Repo:** ~/projects/aether

---

## Overview

Aether is a room-scale operating system that turns a physical space into a living, context-aware environment. A single daemon fuses webcam presence detection with a circadian lighting engine, controlling every light in the room through a unified state machine.

The MVP delivers two states (PRESENT/AWAY), human-only presence detection via the C920 webcam, and time-of-day lighting across 5 Govee devices via MQTT.

---

## MVP Scope (Phase 1)

### In Scope
- C920 webcam → MediaPipe human pose detection (CPU-only, dogs ignored)
- State machine: PRESENT ↔ AWAY (10-second absence timer)
- Circadian Forge: sunrise/sunset API (Open-Meteo) + config-driven color palettes
- Govee control via MQTT → govee2mqtt (2 neon ropes, TV backlight, floor lamp, table lamp)
- Compressed sunrise return sequence (8-second ramp on PRESENT re-entry)
- AWAY alerts: console log + floor lamp amber flash (3x)
- Config: YAML at `~/.config/aether/config.yaml` with Pydantic validation
- `aether discover` CLI command for device-to-zone mapping
- `aether status` CLI command for current state inspection
- Systemd user service

### Out of Scope (tracked for Phase 2+)

| Feature | Phase | Depends On |
|---------|-------|------------|
| FOCUS state + Pomodoro timer | 2 | State machine extensibility |
| PARTY state + DJ Lightshow (madmom beat detection) | 2 | PipeWire audio tap, priority mixer |
| SLEEP state + cascade shutdown | 2 | State machine + bedroom lamp timing |
| Sentry video clip recording | 2 | OpenCV VideoWriter, storage management |
| Vox voice commands (faster-whisper + Ollama intent) | 3 | UM02 mic pipeline, intent classifier |
| Hand gesture control (MediaPipe hands) | 3 | Gesture→command mapping, state-aware filtering |
| OpenRGB desk peripheral integration (keyboard, mouse, case, mobo) | 3 | OpenRGB daemon, MQTT consumer |
| Go light controller + priority mixer | 3 | Needed when multiple systems compete for light control |
| Push notifications (ntfy.sh / Telegram) | 3 | Notification plugin interface |
| Face-Driven Ambient (emotion-reactive room) | 4 | MediaPipe face mesh, expression classifier |
| Posture Sentinel (ergonomic monitoring) | 4 | MediaPipe pose scoring, feedback thresholds |
| Eye Tracker (gaze heatmap) | 4 | MediaPipe face mesh, screen calibration |
| ESP32 integrations (CO2, temperature array, plant monitor) | 4 | MQTT topics, hardware purchased |
| Context switching (Desk Button / NFC Tags) | 4 | Room mode profiles, app/audio routing |

---

## Hardware

### Govee Smart Lighting (MVP)
- **RGBIC Neon Rope Light x2** — wall-mounted, 15-50 segments each
- **RGBIC TV Backlight** — behind 3440x1440 ultrawide, 12-20 segments
- **Floor Lamp Basic** — 1-3 zones, room anchor light
- **Table Lamp (bedroom)** — single zone, sleep/ambient

### Govee Control Methods
| Method | Latency | Segments | Offline | Used For |
|--------|---------|:--------:|:-------:|----------|
| LAN API (UDP:4003) | 5-30ms | No | Yes | Real-time whole-device color |
| Cloud API v2 | 200-2000ms | Yes | No | Segment control on ropes/backlight |
| BLE | 50-200ms | Reverse-eng | Yes | Fallback |

govee2mqtt handles method selection automatically.

### Sensors (MVP)
- **Logitech C920 PRO HD Webcam** — /dev/video0

### Environment Constraints
- Two dogs in the house — all detection is human-only via MediaPipe pose (33-point skeletal mesh)
- Work computer is behind main desk — presence tracks whole room, not desk-facing
- AWAY triggers after no human detected anywhere in C920 FOV for 10 seconds

### Compute
- 8-core CPU, 32GB RAM
- RTX 4070 Ti (12GB VRAM) — kept free for Ollama/gaming; MediaPipe runs on CPU
- CachyOS / KDE Wayland

---

## Architecture

### Process Architecture

```
┌──────────────────────────────────────────────┐
│              aether (Python)                  │
│                                               │
│  ┌───────────┐    ┌──────────────────────┐   │
│  │  Vision   │    │    State Machine     │   │
│  │  Pipeline │───▶│                      │   │
│  │           │    │  PRESENT ◄──► AWAY   │   │
│  │  C920 +   │    │                      │   │
│  │  MediaPipe│    │  10s absence timer   │   │
│  └───────────┘    └──────────┬───────────┘   │
│                              │               │
│                   ┌──────────▼───────────┐   │
│                   │   Circadian Engine   │   │
│                   │                      │   │
│                   │  sunrise/sunset API  │   │
│                   │  + config palettes   │   │
│                   │  + return ramp       │   │
│                   └──────────┬───────────┘   │
│                              │               │
│                   ┌──────────▼───────────┐   │
│                   │   MQTT Publisher     │   │
│                   │   (paho-mqtt)        │   │
│                   └──────────┬───────────┘   │
└──────────────────────────────┼───────────────┘
                               │
                    ┌──────────▼───────────┐
                    │     mosquitto        │
                    │     (MQTT broker)    │
                    └──────────┬───────────┘
                               │
                    ┌──────────▼───────────┐
                    │     govee2mqtt       │
                    │  (LAN + Cloud + BLE) │
                    └──────────┬───────────┘
                               │
              ┌────────┬───────┼───────┬──────────┐
              ▼        ▼       ▼       ▼          ▼
          Rope L   Rope R   TV BL   Floor    Table
                                     Lamp     Lamp
```

### Data Flow

1. **Every 333ms (3fps):** C920 frame → `asyncio.to_thread(VideoCapture.read)` → MediaPipe pose estimation → boolean: human detected?
2. **Presence tracker:** Maintains `last_human_seen` timestamp. If `now - last_human_seen > 10s` → emit AWAY transition. If human detected while AWAY → emit PRESENT transition.
3. **State machine:** Receives transition events. Updates current state. Notifies Circadian Engine of state changes.
4. **Circadian Engine:** Tick loop at 1/sec (steady-state) or 10/sec (during ramps). Computes target colors per zone from time-of-day + config palette. On AWAY → dims to nightlight palette. On PRESENT return → 8-second compressed sunrise ramp then resumes circadian.
5. **MQTT Publisher:** Zone commands published to `aether/light/zone/{name}` as JSON.
6. **govee2mqtt:** Translates MQTT messages to Govee device commands.

### Resource Budget

Target: **<2% CPU, <300MB RAM** in steady-state.

| Component | Steady-State | During Ramp | Notes |
|-----------|-------------|-------------|-------|
| MediaPipe pose | ~1-3% CPU | Same | 3fps, CPU-only |
| Circadian tick | Negligible | ~0.5% CPU | 1/sec → 10/sec for 8s |
| MQTT publish | Negligible | Negligible | Tiny JSON payloads |
| RAM (MediaPipe) | ~200MB | Same | Loaded once |
| RAM (Python + libs) | ~50-80MB | Same | |
| GPU | 0% | 0% | Kept free |

---

## MQTT Topic Contract

Designed for the full Aether vision. MVP publishes the subset marked with ✓.

| Topic | Payload | MVP | Retained |
|-------|---------|:---:|:--------:|
| `aether/state` | `"present"` / `"away"` | ✓ | Yes |
| `aether/state/transition` | `{"from": "away", "to": "present", "reason": "human_detected", "timestamp": "..."}` | ✓ | No |
| `aether/presence/human` | `true` / `false` | ✓ | Yes |
| `aether/presence/last_seen` | ISO 8601 timestamp | ✓ | Yes |
| `aether/light/zone/wall_left` | `{"r": 255, "g": 180, "b": 60, "brightness": 80}` | ✓ | Yes |
| `aether/light/zone/wall_right` | Same format | ✓ | Yes |
| `aether/light/zone/monitor` | Same format | ✓ | Yes |
| `aether/light/zone/floor` | Same format | ✓ | Yes |
| `aether/light/zone/bedroom` | Same format | ✓ | Yes |
| `aether/light/zone/all` | Broadcast to all zones | ✓ | No |
| `aether/alert/sentry` | `{"type": "human_detected", "timestamp": "..."}` | ✓ | No |
| `aether/voice/command` | `{"command": "...", "confidence": 0.9}` | | No |
| `aether/gesture/event` | `{"gesture": "wave", "confidence": 0.8}` | | No |
| `aether/dj/beat` | `{"timestamp": "...", "strength": 0.9}` | | No |
| `aether/dj/bpm` | `120` | | Yes |
| `aether/mode` | `"coding"` / `"gaming"` / `"movie"` / `"dnd"` / `"sleep"` | | Yes |

---

## Configuration

### File Location
`~/.config/aether/config.yaml`

First run with no config → writes defaults from `config.example.yaml` and warns. `aether discover` populates device mappings interactively.

### Schema

```yaml
location:
  latitude: null        # Required — for sunrise/sunset API
  longitude: null       # Required — for sunrise/sunset API

presence:
  camera_index: 0                # /dev/video index
  absence_timeout_sec: 10        # Seconds before AWAY transition
  detection_confidence: 0.5      # MediaPipe min detection confidence
  frame_interval_ms: 333         # ~3fps (configurable)

mqtt:
  broker: localhost
  port: 1883
  topic_prefix: aether

circadian:
  update_interval_sec: 1         # Steady-state tick rate
  ramp_interval_ms: 100          # Tick rate during transitions (10/sec)
  return_ramp_sec: 8             # Compressed sunrise duration
  sunrise_offset_min: 0          # Shift API sunrise ± minutes
  sunset_offset_min: 0           # Shift API sunset ± minutes
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
    nightlight:                  # AWAY state
      color: [180, 140, 60]
      brightness: 5

zones:
  wall_left:
    govee_device: null           # Populated by `aether discover`
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

---

## Project Structure

```
aether/
├── pyproject.toml
├── config.example.yaml
├── CLAUDE.md
├── README.md
├── docs/
│   └── superpowers/
│       └── specs/
│           └── 2026-03-27-aether-design.md
├── src/
│   └── aether/
│       ├── __init__.py
│       ├── __main__.py          # Entry point: python -m aether
│       ├── cli.py               # Click CLI: run, discover, status
│       ├── config.py            # Pydantic config model + loader
│       ├── state.py             # State machine (enum + transition table)
│       ├── vision/
│       │   ├── __init__.py
│       │   ├── camera.py        # C920 capture loop (async via to_thread)
│       │   └── presence.py      # MediaPipe pose → human yes/no + timer
│       ├── lighting/
│       │   ├── __init__.py
│       │   ├── circadian.py     # Sunrise API + palette engine + tick loop
│       │   ├── zones.py         # Zone definitions + color targets
│       │   └── ramp.py          # Color interpolation for transitions
│       ├── adapters/
│       │   ├── __init__.py
│       │   ├── mqtt.py          # paho-mqtt wrapper (connect, publish, subscribe)
│       │   └── govee.py         # GoveeAdapter: zone commands → govee2mqtt topics
│       └── alerts/
│           ├── __init__.py
│           └── sentry.py        # AWAY human detection → log + flash
├── tests/
│   ├── test_state.py
│   ├── test_circadian.py
│   ├── test_presence.py
│   └── test_govee_adapter.py
└── systemd/
    └── aether.service
```

### Module Responsibilities

**`cli.py`** — Click-based CLI with three commands:
- `aether run` — starts the daemon (main async loop)
- `aether discover` — queries govee2mqtt MQTT discovery, lists devices with names/SKUs, interactive zone mapping, flash-tests each device, writes to config
- `aether status` — reads MQTT retained messages, prints current state + zone colors + presence info

**`config.py`** — Pydantic BaseSettings model. Loads from YAML. Missing file → copies `config.example.yaml` to config path and warns. Invalid values → clear error with field name. Fetches sunrise/sunset from Open-Meteo at load time (cached for 24h).

**`state.py`** — Enum-based state machine with transition table. MVP: PRESENT ↔ AWAY. Callbacks on enter/exit per state. Phase 2 extends by adding enum values and transition rules — no rewrite needed.

**`vision/camera.py`** — Opens C920 via OpenCV. Yields frames at configured interval (default 333ms). Uses `asyncio.to_thread()` for the blocking `read()` call. Handles camera errors with retry + backoff, logs to stderr.

**`vision/presence.py`** — Receives frames, runs MediaPipe Pose (CPU, `model_complexity=0` for speed). Maintains `last_human_seen` timestamp. Emits events to state machine: `HUMAN_DETECTED` (resets timer) or `HUMAN_ABSENT` (after 10s timeout). Model loaded once at startup.

**`lighting/circadian.py`** — Fetches sunrise/sunset once daily from Open-Meteo (free, no key, async via httpx). Defines time phases (dawn, morning, midday, golden_hour, evening, night) anchored to sunrise/sunset. Tick loop computes current target colors by interpolating between adjacent phases. Publishes zone colors via MQTT.

**`lighting/ramp.py`** — Generic color/brightness interpolation. Input: start state, end state, duration, tick rate. Yields intermediate RGB+brightness values. Used by circadian transitions and the 8-second return sunrise.

**`lighting/zones.py`** — Zone registry. Maps zone names to device configs. Tracks current color per zone. Provides `set_all()` and `set_zone()` methods that feed into the MQTT publisher.

**`adapters/govee.py`** — GoveeAdapter translates Aether's zone commands into govee2mqtt's expected MQTT topic format. Single point of coupling to govee2mqtt. If govee2mqtt is replaced, only this file changes.

**`adapters/mqtt.py`** — Wraps paho-mqtt. Handles connect/reconnect with backoff. Publishes with QoS 1. Retained messages for state and zone colors (so `aether status` works without the daemon). Subscribes for discovery topics.

**`alerts/sentry.py`** — Activated in AWAY state. On human detection: logs to stderr, publishes `aether/alert/sentry` MQTT message, sends 3x amber flash command to floor lamp zone with 500ms intervals.

### Main Loop

```python
async def main():
    config = load_config()
    mqtt = MqttClient(config.mqtt)
    govee = GoveeAdapter(mqtt, config.zones)
    state_machine = StateMachine(on_transition=handle_transition)
    circadian = CircadianEngine(config, govee)
    presence = PresenceDetector(config.presence, state_machine)
    camera = Camera(config.presence.camera_index, config.presence.frame_interval_ms)

    await asyncio.gather(
        camera.run(presence.process_frame),
        circadian.run(),
        mqtt.run(),
    )
```

Single async event loop. No threads except `to_thread()` for camera reads.

---

## Dependencies

### Python Packages
```
mediapipe >= 0.10          # Pose estimation (bundles TFLite runtime)
opencv-python-headless     # Camera capture, no GUI (~150MB smaller than full)
paho-mqtt >= 2.0           # MQTT client
pydantic >= 2.0            # Config validation
httpx                      # Async HTTP for sunrise/sunset API
click                      # CLI framework
```

Transitive: numpy (via mediapipe). Total install: ~400MB.

### External Services
| Service | Install | Runs As | Config |
|---------|---------|---------|--------|
| mosquitto | `pacman -S mosquitto` | `systemctl enable --now mosquitto` | Default config works |
| govee2mqtt | cargo install or GitHub release | systemd user service | Govee API key + device discovery |

### Systemd Unit
```ini
[Unit]
Description=Aether - Living Room Daemon
After=mosquitto.service
Wants=mosquitto.service

[Service]
Type=simple
ExecStart=/usr/bin/python -m aether run
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
```

User service (`systemctl --user`). Restarts on crash with 5-second backoff.

---

## Graceful Degradation

| Failure | Behavior |
|---------|----------|
| Camera not found / disconnected | Log error, retry every 5s. Circadian Forge continues without presence (assumes PRESENT). No state transitions until camera recovers. |
| MediaPipe fails to load | Fatal on startup — exit with clear error message. MediaPipe is the core dependency. |
| MQTT broker unreachable | Log warning, buffer commands in memory (last 10), retry connection every 5s. Presence detection continues. Lights won't update until reconnected. |
| govee2mqtt not running | MQTT publishes succeed (broker accepts them) but lights don't respond. `aether status` shows "no govee2mqtt response" if discovery topics are empty. |
| Sunrise API unreachable | Fall back to previous day's cached sunrise/sunset. If no cache, use hardcoded defaults (6:00 AM / 7:00 PM). |
| Config file missing | Copy `config.example.yaml` to config path, warn, exit asking user to set latitude/longitude. |

---

## State Machine Detail

### States (MVP)

| State | Lighting | Camera Mode | Entered Via | Exited Via |
|-------|----------|-------------|-------------|------------|
| PRESENT | Circadian Forge (time-of-day) | Presence monitoring (whole room) | Human detected in FOV | No human for 10s |
| AWAY | Nightlight (5% warm amber) | Human-only sentry (MediaPipe pose) | 10s absence timeout | Human detected |

### Transitions

```
PRESENT → AWAY:   no human detected for 10 consecutive seconds
AWAY → PRESENT:   human pose detected → 8-second sunrise ramp → circadian resumes
```

### Phase 2 Extensions (not implemented in MVP)

| State | Lighting | Entered Via | Exited Via |
|-------|----------|-------------|------------|
| FOCUS | Locked cool white, ropes 10% | Voice "focus" / palm-hold gesture | Voice "stop focus" / palm-hold |
| PARTY | DJ Lightshow (beat-synced) | Voice "party" / two-hands-up | Voice "stop" / two-hands-down / music stops 2m |
| SLEEP | Cascade shutdown over 5 min | Voice "goodnight" | Wake word / morning alarm |

---

## Circadian Forge Detail

### Phase Anchoring

Sunrise/sunset fetched daily from Open-Meteo API:
```
GET https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&daily=sunrise,sunset&timezone=auto
```

Time phases derived from sunrise/sunset:

| Phase | Start | End |
|-------|-------|-----|
| dawn | sunrise - 30min | sunrise + 30min |
| morning | sunrise + 30min | solar_noon - 1hr |
| midday | solar_noon - 1hr | solar_noon + 2hr |
| golden_hour | sunset - 1.5hr | sunset |
| evening | sunset | sunset + 1.5hr |
| night | sunset + 1.5hr | sunrise - 30min |

Solar noon = midpoint of sunrise and sunset.

Between phases, colors interpolate linearly over 15 minutes for smooth transitions.

### Palettes

Each phase maps to a color + brightness target per zone. MVP: all zones use the same palette. Config allows per-zone overrides in future.

### Return Ramp

On AWAY → PRESENT transition:
1. Capture current zone states (nightlight)
2. Compute circadian target for current time
3. Interpolate from nightlight → target over 8 seconds at 10 ticks/sec (80 steps)
4. Resume normal 1/sec circadian ticks

---

## Alerts Detail (MVP)

### AWAY Human Detection

When state is AWAY and MediaPipe detects a human pose:

1. Log to stderr: `[aether] ALERT: Human detected while AWAY at {timestamp}`
2. Publish to `aether/alert/sentry`: `{"type": "human_detected", "timestamp": "..."}`
3. Flash floor lamp amber 3x: publish color → wait 500ms → publish off → wait 500ms → repeat
4. The alert fires immediately on first human frame. The PRESENT transition still requires 10 continuous seconds of human presence — so a brief appearance (someone walking through) triggers the alert but not the state change. If the human stays 10s, the normal AWAY → PRESENT transition fires with sunrise ramp.

---

## Testing Strategy

### Unit Tests (no hardware needed)
- **test_state.py** — State machine transitions, timer logic, invalid transitions rejected
- **test_circadian.py** — Phase computation from sunrise/sunset times, color interpolation, ramp generation
- **test_presence.py** — Timer logic with mock timestamps (human detected/absent sequences)
- **test_govee_adapter.py** — Zone command → MQTT topic/payload translation

### Integration Tests (need MQTT broker)
- Publish zone command → verify govee2mqtt receives correct format
- State transition → verify correct MQTT messages published with retained flag

### Manual Testing
- `aether discover` — verify device detection and flash test
- Walk in/out of room — verify state transitions and light changes
- Check different times of day — verify circadian palette changes

---

## Open Questions (resolved during brainstorming)

| Question | Decision | Rationale |
|----------|----------|-----------|
| Python or Go for MVP? | Python | MediaPipe/Whisper have best Python bindings. Go extracted later. |
| Circadian timing source? | API + config | Open-Meteo for seasonal accuracy, config for palette control. |
| Return sequence? | 8-sec compressed sunrise | Feels intentional, room "wakes up" for you. |
| Desk RGB in MVP? | No — Govee only | OpenRGB is a separate yak-shave. 80% visual impact from Govee alone. |
| Notifications? | Log + flash for MVP | Push notifications are a plugin concern for later. |
| Frame rate? | 3fps (333ms) | Sufficient for presence, <2% CPU. |
| Camera blocking? | asyncio.to_thread() | Simple, avoids thread pool complexity. |
| MQTT from day one? | Yes | Avoid rewrite. Topic contract serves full vision. |
