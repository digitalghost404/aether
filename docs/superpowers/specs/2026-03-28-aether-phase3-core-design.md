# Aether Phase 3 Core — Priority Mixer, Vox, Gestures: Design Spec

**Date:** 2026-03-28
**Status:** Approved — ready for implementation planning
**Repo:** ~/projects/aether
**Branch:** development
**Depends on:** Phase 2 (complete, merged)

---

## Overview

Phase 3 Core adds three interacting systems to Aether: a **priority mixer** that arbitrates which system controls each light zone, **Vox** voice commands triggered by a wake word ("Aether") via the UM02 USB mic, and **hand gesture** detection via the existing C920 webcam. These three systems are designed together because voice and gestures are consumers of the mixer's claim-based priority model.

OpenRGB desk peripheral integration is a separate spec (Phase 3 Peripherals) since it has an independent output path.

### Constraints

- **Platform API only** — Govee LAN API still blocked by Xfinity XB8. Same ~10 req/sec rate limit.
- **GPU budget** — RTX 4070 Ti (12GB VRAM). faster-whisper uses GPU only when processing a command (~0.5s bursts). Ollama models unload after idle. No persistent GPU reservation.
- **CPU budget** — MediaPipe pose + hand detection at 3fps stays under 5% CPU total.
- **UM02 mic** — available as PipeWire source: `alsa_input.usb-Clip-on_USB_microphone_UM02-00.mono-fallback`

---

## Priority Mixer

### Purpose

Replaces direct ZoneManager access. All systems submit **claims** to the mixer instead of calling `zones.set_zone()` directly. The mixer resolves which claim wins per zone and forwards the result to ZoneManager. This allows voice/gesture overrides to coexist with active modes.

### Claim Model

```
Claim:
  source: str          # "circadian", "focus", "party", "sleep", "voice", "gesture"
  zone: str            # "wall_left", "wall_right", "monitor", "floor", "bedroom"
  color: ColorState
  priority: int        # lower number = higher priority
  ttl_sec: float|None  # None = permanent until released
  created_at: float    # monotonic timestamp
```

### Priority Levels

| Level | Source | TTL | Description |
|-------|--------|-----|-------------|
| 0 | Manual (voice/gesture) | 10 min default, configurable | User explicitly asked for this |
| 1 | Mode (FOCUS/PARTY/SLEEP) | None — cleared on mode exit | Active mode lighting |
| 2 | Circadian | None — always present | Time-of-day base layer |

### Resolution

Per zone, the active claim with the lowest priority number wins. Ties broken by most recent `created_at`. When a claim expires (TTL elapsed) or is explicitly released, the next-highest-priority claim takes over instantly.

### Expiry

The mixer runs a tick loop at 1/sec checking for expired claims. When a claim expires, it's removed and the zone is re-resolved against remaining claims. The result is forwarded to ZoneManager.

### API

```python
class Mixer:
    def submit(self, source: str, zone: str, color: ColorState, priority: int, ttl_sec: float | None = None) -> None
    def submit_all(self, source: str, color: ColorState, priority: int, ttl_sec: float | None = None) -> None
    def release(self, source: str, zone: str) -> None
    def release_all(self, source: str) -> None
    def get_active_claims(self) -> dict[str, Claim]  # zone -> winning claim
    async def run(self) -> None  # expiry tick loop
```

### Integration Contract

After the mixer is introduced, **nothing except the mixer calls `zones.set_zone()` or `zones.set_all()`**. The mixer is the single writer to ZoneManager. This is enforced by convention.

- CircadianEngine: `self._mixer.submit("circadian", "all", target, priority=2)`
- Mode coroutines: `self._mixer.submit("focus", zone, color, priority=1)`, `self._mixer.release_all("focus")` on exit
- Voice/gesture handlers: `self._mixer.submit("voice", zone, color, priority=0, ttl_sec=config.mixer.manual_ttl_sec)`

The `paused` flag stays on ZoneManager. When paused, the mixer skips forwarding resolved claims.

### Module

`src/aether/mixer.py`

---

## Vox (Voice Commands)

### Audio Pipeline

```
UM02 mic (PipeWire) ──► openWakeWord ("Aether") ──► Record 3-5s ──► faster-whisper STT ──► Intent Classifier ──► Action
```

1. **Continuous capture** from UM02 via `pw-cat --record --target <device>`
2. Audio stream fed to **openWakeWord** — lightweight CNN wake word detector, ~2% CPU, custom trained on "Aether"
3. On wake word detection: floor lamp pulse (single white flash) as acknowledgment
4. Capture next 3-5 seconds of audio (or until 1.5s of silence detected)
5. Command audio → **faster-whisper** `small` model (GPU, ~0.5s inference) → raw text
6. Raw text → **keyword matcher** (fast path) or **Ollama qwen3.5:4b** fallback (slow path) → intent
7. Intent → execute action (state machine event, mixer claim, etc.)

### Wake Word

**Library:** openWakeWord — open source, no API key, custom wake words, minimal CPU.

**Word:** "Aether"

**Why not always-listening STT:** The user doesn't want random audio (music, conversations, video calls) being interpreted as commands. Wake word gates all processing.

### STT (Speech-to-Text)

**Library:** faster-whisper

**Model:** `small` — good accuracy for short commands, ~0.5s inference on RTX 4070 Ti. Loaded on-demand when wake word triggers, not kept resident.

**Timeout:** 5 seconds max recording after wake word, or 1.5 seconds of silence (whichever comes first).

### Intent Classification

**Fast path — keyword matcher:**

| Keyword/Phrase | Intent | Action |
|---|---|---|
| "focus" | mode_focus | FOCUS_START event |
| "stop focus" / "end focus" | mode_focus_stop | FOCUS_STOP event |
| "party" / "party mode" | mode_party | PARTY_START event |
| "stop party" | mode_party_stop | PARTY_STOP event |
| "sleep" / "goodnight" | mode_sleep | SLEEP_START event |
| "stop" / "cancel" | mode_stop | stop current active mode |
| "pause" | pause | pause |
| "resume" / "unpause" | resume | resume |
| "brighter" / "bright" | brightness_up | +20 absolute brightness (clamped 0-100) all zones via mixer (manual priority) |
| "dimmer" / "dim" | brightness_down | -20 absolute brightness (clamped 0-100) all zones via mixer (manual priority) |
| "warmer" | color_warmer | shift color temp warm via mixer (manual priority) |
| "cooler" | color_cooler | shift color temp cool via mixer (manual priority) |
| "lights off" | lights_off | all zones off via mixer (manual priority) |
| "lights on" | lights_on | clear all manual claims, circadian resumes |

Keyword matching is case-insensitive substring search. "Can you make it brighter" matches "brighter". Order matters — check multi-word phrases ("stop focus") before single words ("stop").

**Slow path — Ollama fallback:**

If no keyword matches, send the transcription to `qwen3.5:4b` with a structured prompt:

```
Classify this voice command into one of these intents: mode_focus, mode_focus_stop, mode_party, mode_party_stop, mode_sleep, mode_stop, pause, resume, brightness_up, brightness_down, color_warmer, color_cooler, lights_off, lights_on, unknown.

Command: "{transcription}"

Respond with only the intent name.
```

If the response is "unknown" or doesn't match a known intent → no action, log it.

### Audio Feedback

On wake word detection: single white flash on floor lamp (via mixer at manual priority, TTL 1 second). No audio speaker output.

### Module

`src/aether/vox/` package:

| File | Purpose |
|------|---------|
| `__init__.py` | Package init |
| `mic.py` | PipeWire capture from UM02 via pw-cat subprocess |
| `wake.py` | openWakeWord detector wrapping the continuous audio stream |
| `stt.py` | faster-whisper transcription (load on demand, GPU) |
| `intent.py` | Keyword matcher + Ollama fallback classifier |
| `handler.py` | Intent → action execution (mixer claims, state machine events) |

### New Dependencies

- `faster-whisper` — Whisper STT optimized with CTranslate2
- `openwakeword` — lightweight wake word detection

---

## Hand Gestures

### Detection Pipeline

The C920 already captures frames at 3fps for pose detection. A second MediaPipe model — **HandLandmarker** — runs on the same frames. No additional camera, no new dependencies (MediaPipe includes hand landmark support).

Each frame goes through both PoseLandmarker (existing, for presence) and HandLandmarker (new, for gestures). HandLandmarker returns 21 hand landmarks per detected hand. A gesture classifier maps landmark positions to recognized gestures.

### Gesture Vocabulary

| Gesture | Detection Logic | Action |
|---------|----------------|--------|
| Thumbs up | Thumb tip above thumb MCP, all other fingertips below their PIPs | Brighter +20 absolute brightness via mixer (manual priority) |
| Thumbs down | Thumb tip below thumb MCP, all other fingertips below their PIPs | Dimmer -20 absolute brightness via mixer (manual priority) |
| Closed fist hold (3s) | All fingertips below their PIPs for 9 consecutive frames (~3s at 3fps) | Pause/resume toggle |

### Debouncing & Cooldown

- **Thumbs up/down:** Must be detected in 3 consecutive frames (~1 second at 3fps) before firing.
- **Fist hold:** Must be detected in 9 consecutive frames (~3 seconds at 3fps) before firing.
- **Cooldown:** After any gesture fires, 5-second cooldown before the same gesture can fire again.
- **Why these thresholds:** Prevents accidental triggers from momentary hand positions. The fist hold requires sustained intent.

### Feedback

On gesture recognized: single white flash on floor lamp (same as voice feedback — via mixer at manual priority, TTL 1 second).

### CPU Budget

HandLandmarker adds ~1-2% CPU at 3fps. Combined with PoseLandmarker (~1-3%), total vision pipeline stays under 5%.

### Model File

`hand_landmarker.task` downloaded to `~/.cache/aether/` alongside the existing `pose_landmarker_lite.task`.

### Module

`src/aether/vision/gestures.py` — HandLandmarker setup, gesture classifier, debounce/cooldown logic, action dispatch to mixer.

### No New Dependencies

MediaPipe already includes hand landmark support.

---

## Configuration

### New Config Sections

```yaml
mixer:
  manual_ttl_sec: 600          # 10 min default for voice/gesture overrides
  tick_interval_sec: 1         # claim expiry check rate

vox:
  enabled: true
  mic_source: "alsa_input.usb-Clip-on_USB_microphone_UM02-00.mono-fallback"
  wake_word: "aether"
  command_timeout_sec: 5       # max recording after wake word
  silence_timeout_sec: 1.5     # stop recording after this much silence
  whisper_model: "small"       # faster-whisper model size
  ollama_model: "qwen3.5:4b"  # fallback intent classifier
  feedback_flash: true         # floor lamp pulse on wake word

gestures:
  enabled: true
  detection_confidence: 0.5
  consecutive_frames: 3        # frames before thumbs up/down fires
  fist_hold_frames: 9          # ~3 seconds at 3fps for fist hold
  cooldown_sec: 5
  feedback_flash: true
```

### New Pydantic Models

- `MixerConfig` — manual_ttl_sec, tick_interval_sec
- `VoxConfig` — enabled, mic_source, wake_word, command_timeout_sec, silence_timeout_sec, whisper_model, ollama_model, feedback_flash
- `GestureConfig` — enabled, detection_confidence, consecutive_frames, fist_hold_frames, cooldown_sec, feedback_flash

All added as optional fields on `AetherConfig` with defaults matching the YAML above.

---

## CLI

### New Commands

```
aether vox-test    # Start mic pipeline, print wake word detections and transcriptions
```

No new mode commands — voice and gestures map to existing commands and mixer claims.

### Extended Status

`aether status` extended to show:
- Active mixer claims per zone (source, priority, TTL remaining)
- Vox enabled/disabled
- Gestures enabled/disabled
- Last voice command
- Last gesture

---

## MQTT Topics (Phase 3 additions)

| Topic | Payload | Retained |
|-------|---------|:--------:|
| `aether/vox/last_command` | `{"text": "brighter", "intent": "brightness_up", "timestamp": "..."}` | Yes |
| `aether/gesture/last` | `{"gesture": "thumbs_up", "action": "brightness_up", "timestamp": "..."}` | Yes |
| `aether/mixer/claims` | `{"floor": {"source": "voice", "priority": 0, "ttl_remaining": 540}, ...}` | Yes |

---

## File Changes

### New Files

| File | Purpose |
|------|---------|
| `src/aether/mixer.py` | Priority claim registry, resolution, expiry tick loop |
| `src/aether/vox/__init__.py` | Vox package init |
| `src/aether/vox/mic.py` | PipeWire capture from UM02 |
| `src/aether/vox/wake.py` | openWakeWord wake word detector |
| `src/aether/vox/stt.py` | faster-whisper transcription |
| `src/aether/vox/intent.py` | Keyword matcher + Ollama fallback |
| `src/aether/vox/handler.py` | Intent → action execution |
| `src/aether/vision/gestures.py` | Hand landmark detection + gesture classifier |
| `tests/test_mixer.py` | Claim submission, resolution, expiry, priority |
| `tests/test_intent.py` | Keyword matching, Ollama fallback |
| `tests/test_gestures.py` | Gesture classification, debounce, cooldown |

### Modified Files

| File | Changes |
|------|---------|
| `src/aether/config.py` | Add MixerConfig, VoxConfig, GestureConfig models |
| `src/aether/cli.py` | Wire mixer, vox pipeline, gesture detection into daemon; add vox-test command; extend status |
| `src/aether/lighting/circadian.py` | Submit claims to mixer instead of calling zones directly |
| `src/aether/modes/focus.py` | Submit claims to mixer instead of zones |
| `src/aether/modes/sleep.py` | Submit claims to mixer instead of zones |
| `src/aether/modes/dj.py` | Submit claims to mixer instead of zones |
| `src/aether/vision/presence.py` | Run HandLandmarker alongside PoseLandmarker, feed gestures module |
| `config.example.yaml` | Add mixer, vox, gestures sections |
| `pyproject.toml` | Add faster-whisper, openwakeword |
| `CLAUDE.md` | Add Phase 3 commands and architecture |

---

## Dependencies

### New

| Package | Purpose | Size Impact |
|---------|---------|-------------|
| `faster-whisper` | Speech-to-text (CTranslate2 optimized) | ~50MB + downloads model on first use |
| `openwakeword` | Lightweight wake word detection | ~10MB |

### External (no change)

mosquitto, govee2mqtt, PipeWire (already running), Ollama (already available via MCP)

---

## Testing

### New Test Files

| File | Coverage |
|------|----------|
| `test_mixer.py` | Claim submission, per-zone resolution, priority ordering, TTL expiry, release, release_all, paused suppression |
| `test_intent.py` | Keyword matching (exact, substring, multi-word), unknown handling, case insensitivity |
| `test_gestures.py` | Gesture classification from landmark positions, debounce frame counting, cooldown enforcement |

### Extended

| File | New Cases |
|------|-----------|
| `test_circadian.py` | Verify circadian submits claims to mixer (mock mixer) |
| `test_focus.py` | Verify focus submits claims to mixer |

---

## Graceful Degradation

| Failure | Behavior |
|---------|----------|
| UM02 mic not available | Vox disabled, log warning on startup. Gestures and everything else work. |
| openWakeWord fails to load | Vox disabled, log error. |
| faster-whisper fails (no GPU memory) | Log error per attempt. Wake word still detected but commands not processed. Retry next wake word. |
| Ollama unreachable | Keyword matching still works. Only the fallback path is affected — log warning and skip. |
| HandLandmarker fails to load | Gestures disabled, log warning. Pose detection continues. |
| No claims for a zone | Mixer does not write to that zone — last state persists in ZoneManager. |
