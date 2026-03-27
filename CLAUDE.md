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
source .venv/bin/activate.fish
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
