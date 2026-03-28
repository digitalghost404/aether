from __future__ import annotations

import asyncio
import sys
from enum import Enum

from aether.config import SleepConfig
from aether.lighting.ramp import ColorState, generate_ramp


class SleepStage(Enum):
    MONITOR = "monitor"
    ROPES = "ropes"
    FLOOR = "floor"
    BEDROOM = "bedroom"
    COMPLETE = "complete"


class SleepMode:
    STAGE_FRACTIONS: dict[SleepStage, float] = {
        SleepStage.MONITOR: 0.10,
        SleepStage.ROPES: 0.40,
        SleepStage.FLOOR: 0.20,
        SleepStage.BEDROOM: 0.30,
    }

    def __init__(
        self,
        config: SleepConfig,
        mixer,
        mqtt,
        cancel: asyncio.Event,
        pause: asyncio.Event,
    ):
        self._config = config
        self._mixer = mixer
        self._mqtt = mqtt
        self._cancel = cancel
        self._pause = pause
        self.stage = SleepStage.MONITOR
        self.completed = False

    def _publish_stage(self, stage: SleepStage) -> None:
        self._mqtt.publish("aether/sleep/stage", f'"{stage.value}"', retain=True)

    async def _fade_zone(self, zone: str, target: ColorState, duration_sec: float) -> bool:
        claims = self._mixer.get_active_claims()
        if zone in claims:
            start = claims[zone].color
        else:
            start = ColorState(r=255, g=255, b=255, brightness=100)

        if duration_sec <= 0:
            self._mixer.submit("sleep", zone, target, priority=1)
            self._mixer.resolve()
            return self._cancel.is_set()

        step_count = max(1, int(duration_sec / 12))
        interval = duration_sec / step_count

        for step in generate_ramp(start, target, duration_sec, int(interval * 1000)):
            if self._cancel.is_set():
                return True
            while self._pause.is_set():
                await asyncio.sleep(0.5)
                if self._cancel.is_set():
                    return True
            self._mixer.submit("sleep", zone, step, priority=1)
            self._mixer.resolve()
            await asyncio.sleep(interval)

        self._mixer.submit("sleep", zone, target, priority=1)
        self._mixer.resolve()
        return False

    async def run(self) -> None:
        total_sec = self._config.total_duration_min * 60
        off = ColorState(r=0, g=0, b=0, brightness=0)

        try:
            # Stage 1: Monitor + desk fade to off
            self.stage = SleepStage.MONITOR
            self._publish_stage(self.stage)
            print("[aether] SLEEP: fading monitor + desk", file=sys.stderr)
            dur = total_sec * self.STAGE_FRACTIONS[SleepStage.MONITOR]
            if await self._fade_zone("desk", off, dur * 0.5):
                return
            if await self._fade_zone("monitor", off, dur * 0.5):
                return

            # Stage 2: Ropes + tower fade to off
            self.stage = SleepStage.ROPES
            self._publish_stage(self.stage)
            print("[aether] SLEEP: fading ropes + tower", file=sys.stderr)
            dur = total_sec * self.STAGE_FRACTIONS[SleepStage.ROPES]
            warm = ColorState(r=255, g=180, b=60, brightness=30)
            half = dur / 2
            if await self._fade_zone("tower", off, half):
                return
            if await self._fade_zone("wall_left", warm, half):
                return
            if await self._fade_zone("wall_right", warm, half):
                return
            if await self._fade_zone("wall_left", off, half):
                return
            if await self._fade_zone("wall_right", off, half):
                return

            # Stage 3: Floor lamp fade to off
            self.stage = SleepStage.FLOOR
            self._publish_stage(self.stage)
            print("[aether] SLEEP: fading floor lamp", file=sys.stderr)
            dur = total_sec * self.STAGE_FRACTIONS[SleepStage.FLOOR]
            nightlight = ColorState(r=180, g=140, b=60, brightness=10)
            if await self._fade_zone("floor", nightlight, dur * 0.6):
                return
            if await self._fade_zone("floor", off, dur * 0.4):
                return

            # Stage 4: Bedroom lamp fade to deep orange then off
            self.stage = SleepStage.BEDROOM
            self._publish_stage(self.stage)
            print("[aether] SLEEP: fading bedroom lamp", file=sys.stderr)
            dur = total_sec * self.STAGE_FRACTIONS[SleepStage.BEDROOM]
            cfg = self._config
            deep_orange = ColorState(
                r=cfg.bedroom_final_color[0],
                g=cfg.bedroom_final_color[1],
                b=cfg.bedroom_final_color[2],
                brightness=cfg.bedroom_final_brightness,
            )
            if await self._fade_zone("bedroom", deep_orange, dur * 0.8):
                return
            if await self._fade_zone("bedroom", off, dur * 0.2):
                return

            # Complete
            self.stage = SleepStage.COMPLETE
            self._publish_stage(self.stage)
            self.completed = True
            print("[aether] SLEEP: cascade complete", file=sys.stderr)

        except Exception as e:
            print(f"[aether] SLEEP error: {e}", file=sys.stderr)
        finally:
            if not self.completed:
                self._mixer.release_all("sleep")
                self._mixer.resolve()
