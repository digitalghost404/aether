import asyncio
import pytest
from aether.lighting.ramp import ColorState
from aether.modes.sleep import SleepMode, SleepStage
from aether.config import SleepConfig


class FakeMixer:
    def __init__(self):
        self.submissions: list[tuple[str, str, ColorState, int]] = []

    def submit(self, source: str, zone: str, color: ColorState, priority: int, ttl_sec: float | None = None) -> None:
        self.submissions.append((source, zone, color, priority))

    def submit_all(self, source: str, color: ColorState, priority: int, ttl_sec: float | None = None) -> None:
        for zone in ("wall_left", "wall_right", "monitor", "floor", "bedroom"):
            self.submit(source, zone, color, priority)

    def release(self, source: str, zone: str) -> None:
        pass

    def release_all(self, source: str) -> None:
        pass

    def resolve(self) -> None:
        pass

    def get_active_claims(self):
        return {}


class FakeMqtt:
    def __init__(self):
        self.published: list[tuple[str, str]] = []

    def publish(self, topic: str, payload, retain: bool = False) -> None:
        self.published.append((topic, payload))


def make_sleep(duration_min=1):
    cfg = SleepConfig(total_duration_min=duration_min, bedroom_final_color=[200, 100, 30], bedroom_final_brightness=5)
    mx = FakeMixer()
    mqtt = FakeMqtt()
    cancel = asyncio.Event()
    pause = asyncio.Event()
    return SleepMode(cfg, mx, mqtt, cancel, pause), mx, mqtt, cancel


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
    mode, mx, _, cancel = make_sleep()
    cancel.set()
    await mode.run()
    assert mode.stage == SleepStage.MONITOR


@pytest.mark.asyncio
async def test_full_cascade_reaches_complete():
    cfg = SleepConfig(total_duration_min=0, bedroom_final_color=[200, 100, 30], bedroom_final_brightness=5)
    mx = FakeMixer()
    mqtt = FakeMqtt()
    cancel = asyncio.Event()
    pause = asyncio.Event()
    mode = SleepMode(cfg, mx, mqtt, cancel, pause)
    mode.STAGE_FRACTIONS = {s: 0.0 for s in SleepStage if s != SleepStage.COMPLETE}
    mode.STAGE_FRACTIONS[SleepStage.COMPLETE] = 0.0
    await mode.run()
    assert mode.completed
