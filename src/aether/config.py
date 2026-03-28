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
    frame_interval_ms: int = 100


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
    openrgb_devices: list[str] | None = None


class SentryAlertConfig(BaseModel):
    floor_flash_color: list[int] = [255, 180, 0]
    floor_flash_count: int = 3


class AlertsConfig(BaseModel):
    sentry: SentryAlertConfig = SentryAlertConfig()


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
    desk_color: list[int] = [255, 223, 191]
    desk_brightness: int = 80
    tower_brightness: int = 10


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
    tower_beat_sync: bool = True
    desk_accent: bool = True


class SleepConfig(BaseModel):
    total_duration_min: int = 5
    bedroom_final_color: list[int] = [200, 100, 30]
    bedroom_final_brightness: int = 5


class MixerConfig(BaseModel):
    manual_ttl_sec: int = 600
    tick_interval_sec: int = 1


class VoxConfig(BaseModel):
    enabled: bool = True
    mic_source: str = "alsa_input.usb-Clip-on_USB_microphone_UM02-00.mono-fallback"
    wake_word: str = "hey_jarvis"
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


class OpenRGBConfig(BaseModel):
    enabled: bool = False
    host: str = "localhost"
    port: int = 6820
    retry_attempts: int = 3
    retry_delay_sec: float = 2.0


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
    openrgb: OpenRGBConfig = OpenRGBConfig()


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
