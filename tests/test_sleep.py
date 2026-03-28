import asyncio
import pytest
from aether.lighting.ramp import ColorState
from aether.modes.sleep import SleepMode, SleepStage
from aether.config import SleepConfig


class FakeZoneManager:
    def __init__(self):
        self.calls: list[tuple[str, ColorState]] = []
        self.paused = False

    def set_zone(self, zone: str, state: ColorState) -> None:
        self.calls.append((zone, state))

    def get(self, zone: str) -> ColorState:
        return ColorState(r=255, g=255, b=255, brightness=100)


class FakeMqtt:
    def __init__(self):
        self.published: list[tuple[str, str]] = []

    def publish(self, topic: str, payload, retain: bool = False) -> None:
        self.published.append((topic, payload))


def make_sleep(duration_min=1):
    cfg = SleepConfig(total_duration_min=duration_min, bedroom_final_color=[200, 100, 30], bedroom_final_brightness=5)
    zm = FakeZoneManager()
    mqtt = FakeMqtt()
    cancel = asyncio.Event()
    pause = asyncio.Event()
    return SleepMode(cfg, zm, mqtt, cancel, pause), zm, mqtt, cancel


def test_initial_stage():
    mode, _, _, _ = make_sleep()
    assert mode.stage == SleepStage.MONITOR


def test_stages_sequence():
    stages = list(SleepStage)
    assert stages == [
        SleepStage.MONITOR,
        SleepStage.ROPES,
        SleepStage.FLOOR,
        SleepStage.BEDROOM,
        SleepStage.COMPLETE,
    ]


def test_stage_time_fractions_sum_to_one():
    mode, _, _, _ = make_sleep()
    total = sum(mode.STAGE_FRACTIONS.values())
    assert abs(total - 1.0) < 0.01


@pytest.mark.asyncio
async def test_cancel_stops_cascade():
    mode, zm, _, cancel = make_sleep()
    cancel.set()
    await mode.run()
    assert mode.stage == SleepStage.MONITOR


@pytest.mark.asyncio
async def test_full_cascade_reaches_complete():
    cfg = SleepConfig(total_duration_min=0, bedroom_final_color=[200, 100, 30], bedroom_final_brightness=5)
    zm = FakeZoneManager()
    mqtt = FakeMqtt()
    cancel = asyncio.Event()
    pause = asyncio.Event()
    mode = SleepMode(cfg, zm, mqtt, cancel, pause)
    mode.STAGE_FRACTIONS = {s: 0.0 for s in SleepStage if s != SleepStage.COMPLETE}
    mode.STAGE_FRACTIONS[SleepStage.COMPLETE] = 0.0
    await mode.run()
    assert mode.completed
