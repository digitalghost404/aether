# Aether

Room-scale presence-aware circadian lighting daemon. A single async Python process that watches for humans via camera, tracks time of day, and orchestrates Govee smart lights and OpenRGB peripherals into a unified, hands-free lighting experience.

Walk into a room and lights ramp up to match the time of day. Leave and they dim to a nightlight. Say "Aether, focus mode" and a Pomodoro timer takes over your lights. Play music and party mode syncs the room to the beat. At night, a sleep cascade fades each zone in sequence until everything is off.

## Features

- **Presence detection** -- MediaPipe pose estimation via webcam. Detects humans, ignores pets. 10fps at ~6% CPU.
- **Circadian lighting** -- Automatic color temperature and brightness based on sunrise/sunset times for your location. Six time phases (dawn, morning, midday, golden hour, evening, night) with smooth transitions.
- **Scene system** -- 9 predefined scenes with per-segment gradient control on Govee strip lights. Scenes map to circadian phases or can be applied manually.
- **Priority mixer** -- Multiple lighting sources (circadian, modes, voice, gestures) submit claims with priorities. The mixer resolves conflicts per zone, so a voice command temporarily overrides circadian without fighting it.
- **Focus mode** -- Pomodoro timer (25/5/15 by default) with visual feedback. Monitor goes cool white for work, green for breaks. Rope lights dim as the work period progresses.
- **Party mode** -- Captures system audio via PipeWire, runs beat detection with librosa, and pulses accent lights on every beat. Base color shifts across a palette every 8 beats.
- **Sleep cascade** -- 4-stage sequential shutdown over 5 minutes. Monitor and desk first, then ropes, floor, and finally bedroom -- fading through warm colors to off.
- **Voice control** -- Wake word detection ("Aether") via OpenWakeWord, speech-to-text via faster-whisper (GPU-accelerated), keyword-based intent classification. 18 voice intents covering modes, brightness, color, and scenes.
- **Gesture control** -- Hand gesture recognition via MediaPipe hands. Thumbs up/down for brightness, closed fist to pause/resume.
- **OpenRGB peripherals** -- Optional control of keyboard, mouse, case lighting, and RAM LEDs through the OpenRGB SDK.
- **Sentry alerts** -- When the room is in AWAY state and a human is suddenly detected, the floor light flashes orange as an intrusion alert.
- **MQTT integration** -- All state changes, presence events, and zone updates are published to MQTT. External tools can monitor and control the system.

## Architecture

```
C920 webcam
    |
    v
MediaPipe Pose + Hands
    |                  \
    v                   v
PresenceTracker    GestureClassifier
    |                   |
    v                   v
StateMachine <--- VoxHandler <--- faster-whisper <--- OpenWakeWord <--- pw-cat mic
    |
    v
Transition Handler
    |
    +---> CircadianEngine ---> SceneEngine ---|
    +---> FocusMode --------------------------+--> Mixer ---> ZoneManager
    +---> DJMode ------------------------------|       |
    +---> SleepMode ----------------------------|       +---> GoveeAdapter ---> MQTT ---> govee2mqtt ---> Govee lights
                                                        +---> GoveeSegmentAdapter ---> Govee Platform API (segments)
                                                        +---> OpenRGBAdapter ---> OpenRGB Server ---> USB peripherals
```

### State Machine

Five states with event-driven transitions:

| State | Description | Entry |
|-------|-------------|-------|
| **PRESENT** | Human in room, circadian lighting active | Camera detects human |
| **AWAY** | No human for 10s, nightlight mode | Absence timeout |
| **FOCUS** | Pomodoro timer with work/break lighting | Voice/CLI command |
| **PARTY** | Beat-synced DJ lightshow | Voice/CLI command |
| **SLEEP** | 4-stage cascade shutdown | Voice/CLI command |

Modes (FOCUS/PARTY/SLEEP) are sticky -- presence detection is ignored while active. Exiting a mode returns to PRESENT with an 8-second "compressed sunrise" ramp.

### Priority Mixer

Every lighting source submits color claims to zones with a priority level:

| Priority | Source | TTL |
|----------|--------|-----|
| 0 (highest) | Voice / gesture overrides | 10 minutes |
| 1 | Active mode (focus/party/sleep) | Until mode exits |
| 2 (lowest) | Circadian engine | Permanent |

The mixer resolves each zone independently -- the lowest priority number wins. Ties are broken by most recent submission.

### Zones

Seven lighting zones, each backed by a Govee light or OpenRGB device group:

| Zone | Typical Hardware | Segments |
|------|-----------------|----------|
| `wall_left` | Govee LED strip | 22 |
| `wall_right` | Govee LED strip | 22 |
| `monitor` | Govee light bar | 15 |
| `floor` | Govee floor lamp | 7 |
| `bedroom` | Govee bulb | 1 |
| `desk` | Keyboard, mouse (OpenRGB) | -- |
| `tower` | Case LEDs, RAM (OpenRGB) | -- |

## Scenes

Nine predefined scenes with per-segment gradient support:

| Scene | Description |
|-------|-------------|
| `sunrise` | Cyan-to-orange gradient, warm whites |
| `purple_night` | Deep purple tones across all zones |
| `deep_space` | Dark with scattered starlight highlights |
| `ember` | Warm orange and red firelight |
| `forest` | Natural greens with earthy accents |
| `neon_tokyo` | Magenta/cyan cyberpunk |
| `golden` | Warm golden hour tones |
| `arctic` | Cool blue-white ice |
| `dim_amber` | Ultra-low amber nightlight |

Scenes are defined in `config.yaml` with either solid colors or gradient stops per zone. The circadian engine maps time phases to scenes automatically (configurable in `circadian.phase_scenes`).

## Requirements

### Hardware

- USB webcam (tested with Logitech C920)
- Govee smart lights with LAN/Cloud API support
- USB microphone for voice control (tested with UM02 clip-on)
- PipeWire audio server (for party mode beat detection and mic capture)
- **Optional:** OpenRGB-compatible peripherals (keyboard, mouse, case LEDs, RAM)

### Software

- Python 3.11+
- [mosquitto](https://mosquitto.org/) MQTT broker
- [govee2mqtt](https://github.com/wez/govee2mqtt) bridge
- **Optional:** [OpenRGB](https://openrgb.org/) server for desk peripherals
- **Optional:** NVIDIA GPU + CUDA for faster whisper inference (falls back to CPU)

## Installation

```bash
# Clone
git clone https://github.com/digitalghost404/aether.git
cd aether

# Create virtualenv
python -m venv .venv
source .venv/bin/activate      # bash/zsh
# source .venv/bin/activate.fish  # fish

# Install
pip install -e .

# Optional: OpenRGB peripheral support
pip install -e ".[openrgb]"

# Optional: dev tools
pip install -e ".[dev]"
```

### MediaPipe Model

The pose landmarker model is loaded from `~/.cache/aether/pose_landmarker_lite.task`. Download it from [MediaPipe's model page](https://developers.google.com/mediapipe/solutions/vision/pose_landmarker#models) and place it there.

## Configuration

Copy the example config and edit it:

```bash
mkdir -p ~/.config/aether
cp config.example.yaml ~/.config/aether/config.yaml
```

**Required settings:**

```yaml
location:
  latitude: 40.7128    # Your latitude
  longitude: -74.0060  # Your longitude
```

Then run device discovery to map Govee lights to zones:

```bash
aether discover
```

This interactive tool walks you through assigning each detected Govee device to a zone. Device IDs are written to your config.

### Govee Platform API (for scenes)

Per-segment gradient control requires a Govee Platform API key. Set it as an environment variable:

```bash
export GOVEE_API_KEY="your-api-key-here"
```

Or add it to `config.yaml`:

```yaml
govee_api:
  api_key: "your-api-key-here"
```

### OpenRGB (optional)

```yaml
openrgb:
  enabled: true
  host: localhost
  port: 6742

zones:
  desk:
    openrgb_devices:
      - "SteelSeries Apex 3 TKL"
      - "SteelSeries Rival 600"
  tower:
    openrgb_devices:
      - "Corsair Lighting Node"
      - "XPG RAM"
```

Run `openrgb --list-devices` to find exact device names.

### Voice Control

```yaml
vox:
  enabled: true
  mic_source: "alsa_input.usb-YOUR_MIC_ID.mono-fallback"
  wake_word: "hey_jarvis"    # OpenWakeWord model name
  whisper_model: "small"     # tiny/base/small/medium
```

Find your mic source with `pw-cli list-objects | grep alsa_input`.

## Usage

### Start the Daemon

```bash
# Ensure MQTT broker is running
systemctl --user start mosquitto

# Optional: start OpenRGB server
systemctl --user start openrgb-server

# Run
aether run
```

### CLI Commands

```bash
# Modes
aether focus              # Start Pomodoro focus session
aether focus-stop         # Exit focus mode
aether party              # Start DJ lightshow (play music first)
aether party-stop         # Stop party mode
aether sleep              # Start cascade shutdown
aether sleep-stop         # Cancel sleep cascade

# Playback
aether pause              # Pause all light output
aether resume             # Resume light output

# Scenes
aether scene sunrise      # Apply a scene
aether scene --random     # Random scene
aether scene --reset      # Return to circadian
aether scene --list       # List available scenes

# Utilities
aether status             # Check current state
aether discover           # Map devices to zones
aether vox-test           # Test voice pipeline
```

### Voice Commands

Say the wake word ("Aether" or configured alternative), then:

| Command | Action |
|---------|--------|
| "focus mode" | Start Pomodoro |
| "stop focus" | Exit focus mode |
| "party mode" | Start DJ lightshow |
| "bedtime" / "sleep" | Start sleep cascade |
| "pause" / "freeze" | Pause output |
| "resume" / "continue" | Resume output |
| "brighter" | Brightness +20% |
| "dimmer" | Brightness -20% |
| "warmer" | Shift warmer (more red) |
| "cooler" | Shift cooler (more blue) |
| "lights off" | All zones to black |
| "lights on" | Release voice overrides |
| "set scene [name]" | Apply a scene |
| "random scene" | Random scene |
| "reset scene" | Return to circadian |

### Gestures

| Gesture | Action |
|---------|--------|
| Thumbs up | Brightness +20% |
| Thumbs down | Brightness -20% |
| Closed fist (hold) | Toggle pause/resume |

Gestures require 3 consecutive frames of confirmation (9 for fist) with a 5-second cooldown to prevent accidental triggers.

### Systemd Service

```bash
# Install the service
mkdir -p ~/.config/systemd/user
cp systemd/aether.service ~/.config/systemd/user/

# Edit the service to set your GOVEE_API_KEY
systemctl --user edit aether

# Enable and start
systemctl --user enable aether
systemctl --user start aether

# View logs
journalctl --user -u aether -f
```

The service depends on `mosquitto.service` and `openrgb-server.service` (optional), restarts on failure with a 10-second delay.

## MQTT Topics

### Published by Aether

| Topic | Payload | Description |
|-------|---------|-------------|
| `aether/state` | `"PRESENT"` | Current state machine state |
| `aether/state/transition` | `{from, to, reason, ts}` | State transition records |
| `aether/presence/human` | `true/false` | Human detected in frame |
| `aether/presence/last_seen` | ISO timestamp | Last human detection time |
| `aether/light/zone/{zone}` | `{r, g, b, brightness}` | Current zone color |

### Subscribed by Aether

| Topic | Payload | Description |
|-------|---------|-------------|
| `aether/mode/set` | `"focus"/"party"/"sleep"/"stop"` | Mode control |
| `aether/control` | `"pause"/"resume"` | Playback control |
| `aether/scene/set` | `"name"/"random"/"reset"` | Scene control |

## Development

```bash
# Activate virtualenv
source .venv/bin/activate.fish

# Run tests (21 test files, 190+ tests)
pytest

# Run with verbose logging
aether run --config ~/.config/aether/config.yaml
```

### Project Structure

```
src/aether/
    __main__.py          # Entry point
    cli.py               # Click CLI commands
    config.py            # Pydantic config schema + YAML loading
    state.py             # Finite state machine (5 states, 9 events)
    mixer.py             # Priority-based claim resolver

    vision/
        camera.py        # OpenCV async capture with retry
        presence.py      # MediaPipe pose detection + tracking
        gestures.py      # Hand gesture classification (thumbs/fist)

    lighting/
        ramp.py          # ColorState dataclass + interpolation
        zones.py         # Zone manager (7 zones, multi-adapter routing)
        circadian.py     # Sunrise/sunset phase engine

    adapters/
        govee.py         # Govee control via MQTT (govee2mqtt)
        govee_segment.py # Govee Platform API (per-segment gradients)
        mqtt.py          # MQTT client wrapper (auto-reconnect, buffering)
        openrgb.py       # OpenRGB SDK adapter (desk peripherals)

    scenes/
        engine.py        # Scene application engine
        interpolate.py   # Gradient stop interpolation

    modes/
        focus.py         # Pomodoro timer with visual feedback
        dj.py            # Beat-synced party mode (librosa)
        sleep.py         # 4-stage cascade shutdown

    vox/
        mic.py           # PipeWire mic capture (pw-cat)
        wake.py          # Wake word detection (OpenWakeWord)
        stt.py           # Speech-to-text (faster-whisper, GPU/CPU)
        intent.py        # Keyword-based intent classification
        handler.py       # Intent execution (state/mixer/scene dispatch)

    alerts/
        sentry.py        # Intrusion alert (floor flash on unexpected presence)
```

## Known Limitations

- **Govee Platform API rate limit** is ~1 request/second. Applying a scene across 4 segmented devices takes ~30 seconds. Color quantization (step=16) reduces API calls by ~70%.
- **Wake word model** uses OpenWakeWord's pretrained models. Custom "Aether" wake word requires training a custom model; the default config uses "hey_jarvis" as a stand-in.
- **Single camera** -- only one camera is supported. Multi-room setups would need multiple aether instances.
- **PipeWire required** for both voice (mic capture via `pw-cat`) and party mode (audio tap from speaker sink).

## License

Private project. Not currently licensed for redistribution.
