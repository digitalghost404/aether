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
