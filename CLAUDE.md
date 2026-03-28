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
- **librosa** — beat tracking for PARTY mode

## External Dependencies

- **mosquitto** — MQTT broker (`systemctl --user start mosquitto`)
- **govee2mqtt** — Govee device bridge

## Commands

```bash
# Development
source .venv/bin/activate.fish
python -m aether run              # Start daemon
python -m aether discover         # Map Govee devices to zones
python -m aether status           # Check current state
pytest                            # Run tests

# Phase 2 modes
python -m aether focus             # Start Pomodoro focus session
python -m aether focus-stop        # Exit focus mode
python -m aether party             # Start DJ lightshow
python -m aether party-stop        # Stop party mode
python -m aether sleep             # Start cascade shutdown
python -m aether sleep-stop        # Cancel sleep cascade
python -m aether pause             # Pause all light output
python -m aether resume            # Resume light output

# Systemd
systemctl --user enable aether
systemctl --user start aether
journalctl --user -u aether -f   # View logs
```

## Architecture

Single Python async process: C920 → MediaPipe pose → state machine (PRESENT/AWAY/FOCUS/PARTY/SLEEP) → circadian engine + mode coroutines → MQTT → govee2mqtt → Govee lights.

## Config

`~/.config/aether/config.yaml` — copy from `config.example.yaml`.
Set `location.latitude` and `location.longitude` for sunrise/sunset times.
Run `aether discover` to map Govee devices to zones.

## Design Specs

- `docs/superpowers/specs/2026-03-27-aether-design.md` — Phase 1 (MVP)
- `docs/superpowers/specs/2026-03-27-aether-phase2-design.md` — Phase 2 (FOCUS/PARTY/SLEEP)
