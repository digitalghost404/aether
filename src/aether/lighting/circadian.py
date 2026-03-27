from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from aether.config import AetherConfig, PaletteEntry
from aether.lighting.ramp import ColorState, generate_ramp
from aether.lighting.zones import ZoneManager
from aether.state import State


@dataclass
class SunTimes:
    sunrise: datetime
    sunset: datetime

    @property
    def solar_noon(self) -> datetime:
        return self.sunrise + (self.sunset - self.sunrise) / 2


CACHE_PATH = Path.home() / ".cache" / "aether" / "sun_times.json"


def get_default_sun_times() -> SunTimes:
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return SunTimes(
        sunrise=today.replace(hour=6, minute=0),
        sunset=today.replace(hour=19, minute=0),
    )


async def fetch_sun_times(lat: float, lon: float) -> SunTimes:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "daily": "sunrise,sunset",
                    "timezone": "auto",
                    "forecast_days": 1,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            sunrise_str = data["daily"]["sunrise"][0]
            sunset_str = data["daily"]["sunset"][0]

            sunrise = datetime.fromisoformat(sunrise_str)
            sunset = datetime.fromisoformat(sunset_str)

            CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            CACHE_PATH.write_text(json.dumps({
                "sunrise": sunrise.isoformat(),
                "sunset": sunset.isoformat(),
            }))

            return SunTimes(sunrise=sunrise, sunset=sunset)
    except Exception as e:
        print(f"[aether] Sunrise API failed: {e}. Trying cache...", file=sys.stderr)
        return _load_cached_or_default()


def _load_cached_or_default() -> SunTimes:
    try:
        data = json.loads(CACHE_PATH.read_text())
        return SunTimes(
            sunrise=datetime.fromisoformat(data["sunrise"]),
            sunset=datetime.fromisoformat(data["sunset"]),
        )
    except Exception:
        print("[aether] No cache. Using defaults (6:00 AM / 7:00 PM).", file=sys.stderr)
        return get_default_sun_times()


def compute_phase(now: datetime, sun: SunTimes) -> str:
    dawn_start = sun.sunrise - timedelta(minutes=30)
    dawn_end = sun.sunrise + timedelta(minutes=30)
    morning_end = sun.solar_noon - timedelta(hours=1)
    midday_end = sun.solar_noon + timedelta(hours=2)
    golden_start = sun.sunset - timedelta(hours=1, minutes=30)
    evening_end = sun.sunset + timedelta(hours=1, minutes=30)

    if dawn_start <= now < dawn_end:
        return "dawn"
    elif dawn_end <= now < morning_end:
        return "morning"
    elif morning_end <= now < midday_end:
        return "midday"
    elif golden_start <= now < sun.sunset:
        return "golden_hour"
    elif sun.sunset <= now < evening_end:
        return "evening"
    else:
        return "night"


def phase_color(phase: str, palettes: dict[str, ColorState]) -> ColorState:
    return palettes[phase]


def palettes_from_config(config: AetherConfig) -> dict[str, ColorState]:
    result = {}
    for name, entry in config.circadian.palettes.items():
        result[name] = ColorState(
            r=entry.color[0], g=entry.color[1], b=entry.color[2],
            brightness=entry.brightness,
        )
    return result


class CircadianEngine:
    def __init__(self, config: AetherConfig, zones: ZoneManager):
        self._config = config
        self._zones = zones
        self._palettes = palettes_from_config(config)
        self._sun: SunTimes | None = None
        self._last_fetch_date: str | None = None
        self._ramping = False
        self._state = State.PRESENT

    async def _ensure_sun_times(self) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._last_fetch_date == today and self._sun is not None:
            return

        loc = self._config.location
        if loc.latitude is not None and loc.longitude is not None:
            self._sun = await fetch_sun_times(loc.latitude, loc.longitude)
        else:
            self._sun = get_default_sun_times()
        self._last_fetch_date = today

    def on_state_change(self, new_state: State) -> None:
        self._state = new_state

    async def run_return_ramp(self) -> None:
        if self._sun is None:
            return

        self._ramping = True
        nightlight = self._palettes.get("nightlight", ColorState(180, 140, 60, 5))
        now = datetime.now(timezone.utc)
        phase = compute_phase(now, self._sun)
        target = phase_color(phase, self._palettes)

        for step in generate_ramp(
            nightlight, target,
            duration_sec=self._config.circadian.return_ramp_sec,
            interval_ms=self._config.circadian.ramp_interval_ms,
        ):
            self._zones.set_all(step)
            await asyncio.sleep(self._config.circadian.ramp_interval_ms / 1000.0)

        self._ramping = False

    async def run(self) -> None:
        while True:
            if self._ramping:
                await asyncio.sleep(0.1)
                continue

            await self._ensure_sun_times()

            if self._state == State.AWAY:
                nightlight = self._palettes.get("nightlight", ColorState(180, 140, 60, 5))
                self._zones.set_all(nightlight)
            elif self._sun is not None:
                now = datetime.now(timezone.utc)
                phase = compute_phase(now, self._sun)
                target = phase_color(phase, self._palettes)
                self._zones.set_all(target)

            await asyncio.sleep(self._config.circadian.update_interval_sec)
