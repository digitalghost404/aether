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
    steps = int(duration_sec * 1000 / interval_ms)
    for i in range(steps):
        t = (i + 1) / steps
        yield interpolate(start, end, t)
