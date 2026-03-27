from datetime import datetime, time, timezone, timedelta
import pytest
from aether.lighting.circadian import (
    SunTimes,
    compute_phase,
    phase_color,
    CircadianEngine,
    get_default_sun_times,
)
from aether.lighting.ramp import ColorState


PALETTES = {
    "dawn": ColorState(r=255, g=160, b=50, brightness=30),
    "morning": ColorState(r=255, g=240, b=220, brightness=80),
    "midday": ColorState(r=255, g=255, b=255, brightness=100),
    "golden_hour": ColorState(r=255, g=180, b=60, brightness=70),
    "evening": ColorState(r=80, g=60, b=180, brightness=40),
    "night": ColorState(r=30, g=20, b=80, brightness=15),
    "nightlight": ColorState(r=180, g=140, b=60, brightness=5),
}

# Sunrise at 6:30, sunset at 19:00 (7 PM)
SUN = SunTimes(
    sunrise=datetime(2026, 3, 27, 6, 30, tzinfo=timezone.utc),
    sunset=datetime(2026, 3, 27, 19, 0, tzinfo=timezone.utc),
)


def test_dawn_phase():
    t = datetime(2026, 3, 27, 6, 15, tzinfo=timezone.utc)
    assert compute_phase(t, SUN) == "dawn"


def test_morning_phase():
    t = datetime(2026, 3, 27, 8, 0, tzinfo=timezone.utc)
    assert compute_phase(t, SUN) == "morning"


def test_midday_phase():
    t = datetime(2026, 3, 27, 12, 45, tzinfo=timezone.utc)
    assert compute_phase(t, SUN) == "midday"


def test_golden_hour_phase():
    t = datetime(2026, 3, 27, 18, 0, tzinfo=timezone.utc)
    assert compute_phase(t, SUN) == "golden_hour"


def test_evening_phase():
    t = datetime(2026, 3, 27, 19, 30, tzinfo=timezone.utc)
    assert compute_phase(t, SUN) == "evening"


def test_night_phase():
    t = datetime(2026, 3, 27, 22, 0, tzinfo=timezone.utc)
    assert compute_phase(t, SUN) == "night"


def test_phase_color_returns_palette():
    color = phase_color("dawn", PALETTES)
    assert color == PALETTES["dawn"]


def test_fetch_sun_times_fallback():
    defaults = get_default_sun_times()
    assert defaults.sunrise.hour == 6
    assert defaults.sunset.hour == 19
