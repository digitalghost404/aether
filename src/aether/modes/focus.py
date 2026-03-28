from __future__ import annotations

import asyncio
import sys
from enum import Enum

from aether.config import FocusConfig
from aether.lighting.ramp import ColorState


class PomodoroPhase(Enum):
    WORK = "work"
    SHORT_BREAK = "short_break"
    LONG_BREAK = "long_break"


class FocusMode:
    def __init__(
        self,
        config: FocusConfig,
        mixer,
        cancel: asyncio.Event,
        pause: asyncio.Event,
    ):
        self._config = config
        self._mixer = mixer
        self._cancel = cancel
        self._pause = pause
        self.phase = PomodoroPhase.WORK
        self.cycle = 1
        self._total_cycles = config.cycles
        self._work_in_cycle = 0  # 0 = on work, 1 = on break within cycle

    def _advance(self) -> bool:
        """Advance to next phase. Returns True if all cycles complete."""
        if self.phase == PomodoroPhase.WORK:
            if self._total_cycles > 0 and self.cycle >= self._total_cycles:
                self.phase = PomodoroPhase.LONG_BREAK
            else:
                self.phase = PomodoroPhase.SHORT_BREAK
        elif self.phase in (PomodoroPhase.SHORT_BREAK, PomodoroPhase.LONG_BREAK):
            if self.phase == PomodoroPhase.LONG_BREAK:
                return True
            self.cycle += 1
            if self._total_cycles > 0 and self.cycle > self._total_cycles:
                return True
            self.phase = PomodoroPhase.WORK
        return False

    def _rope_brightness(self, progress: float) -> int:
        dim = self._config.rope_dim_brightness
        return round(dim + (100 - dim) * progress)

    def _apply_work_lighting(self, progress: float) -> None:
        cfg = self._config
        self._mixer.submit(
            "focus", "monitor",
            ColorState(r=cfg.work_color[0], g=cfg.work_color[1], b=cfg.work_color[2], brightness=cfg.work_brightness),
            priority=1,
        )
        rope_br = self._rope_brightness(progress)
        rope_color = ColorState(r=180, g=140, b=60, brightness=rope_br)
        self._mixer.submit("focus", "wall_left", rope_color, priority=1)
        self._mixer.submit("focus", "wall_right", rope_color, priority=1)
        off = ColorState(r=0, g=0, b=0, brightness=0)
        self._mixer.submit("focus", "floor", off, priority=1)
        self._mixer.submit("focus", "bedroom", off, priority=1)
        desk = ColorState(r=cfg.desk_color[0], g=cfg.desk_color[1], b=cfg.desk_color[2], brightness=cfg.desk_brightness)
        self._mixer.submit("focus", "desk", desk, priority=1)
        tower = ColorState(r=0, g=0, b=0, brightness=cfg.tower_brightness)
        self._mixer.submit("focus", "tower", tower, priority=1)
        self._mixer.resolve()

    def _apply_break_lighting(self) -> None:
        cfg = self._config
        self._mixer.submit(
            "focus", "monitor",
            ColorState(r=cfg.work_color[0], g=cfg.work_color[1], b=cfg.work_color[2], brightness=60),
            priority=1,
        )
        break_color = ColorState(
            r=cfg.break_color[0], g=cfg.break_color[1], b=cfg.break_color[2],
            brightness=cfg.break_brightness,
        )
        self._mixer.submit("focus", "wall_left", break_color, priority=1)
        self._mixer.submit("focus", "wall_right", break_color, priority=1)
        off = ColorState(r=0, g=0, b=0, brightness=0)
        self._mixer.submit("focus", "floor", off, priority=1)
        self._mixer.submit("focus", "bedroom", off, priority=1)
        desk = ColorState(r=cfg.desk_color[0], g=cfg.desk_color[1], b=cfg.desk_color[2], brightness=cfg.desk_brightness)
        self._mixer.submit("focus", "desk", desk, priority=1)
        tower = ColorState(r=0, g=0, b=0, brightness=cfg.tower_brightness)
        self._mixer.submit("focus", "tower", tower, priority=1)
        self._mixer.resolve()

    def _apply_long_break_lighting(self) -> None:
        cfg = self._config
        self._mixer.submit(
            "focus", "monitor",
            ColorState(r=cfg.work_color[0], g=cfg.work_color[1], b=cfg.work_color[2], brightness=60),
            priority=1,
        )
        amber = ColorState(r=255, g=180, b=60, brightness=70)
        self._mixer.submit("focus", "wall_left", amber, priority=1)
        self._mixer.submit("focus", "wall_right", amber, priority=1)
        off = ColorState(r=0, g=0, b=0, brightness=0)
        self._mixer.submit("focus", "floor", off, priority=1)
        self._mixer.submit("focus", "bedroom", off, priority=1)
        desk = ColorState(r=cfg.desk_color[0], g=cfg.desk_color[1], b=cfg.desk_color[2], brightness=cfg.desk_brightness)
        self._mixer.submit("focus", "desk", desk, priority=1)
        tower = ColorState(r=0, g=0, b=0, brightness=cfg.tower_brightness)
        self._mixer.submit("focus", "tower", tower, priority=1)
        self._mixer.resolve()

    async def _flash_ropes(self, count: int = 2) -> None:
        bright = ColorState(r=255, g=255, b=255, brightness=100)
        dim = ColorState(r=180, g=140, b=60, brightness=self._config.rope_dim_brightness)
        for _ in range(count):
            self._mixer.submit("focus", "wall_left", bright, priority=1)
            self._mixer.submit("focus", "wall_right", bright, priority=1)
            self._mixer.resolve()
            await asyncio.sleep(0.3)
            self._mixer.submit("focus", "wall_left", dim, priority=1)
            self._mixer.submit("focus", "wall_right", dim, priority=1)
            self._mixer.resolve()
            await asyncio.sleep(0.3)

    async def _wait_with_pause(self, seconds: float) -> bool:
        remaining = seconds
        while remaining > 0:
            if self._cancel.is_set():
                return True
            if self._pause.is_set():
                await asyncio.sleep(0.5)
                continue
            step = min(1.0, remaining)
            await asyncio.sleep(step)
            remaining -= step
        return self._cancel.is_set()

    async def _run_work(self) -> bool:
        total_sec = self._config.work_min * 60
        elapsed = 0.0
        tick = 30.0

        print(f"[aether] FOCUS: work period {self.cycle}/{self._total_cycles or '∞'} ({self._config.work_min}min)", file=sys.stderr)

        while elapsed < total_sec:
            if self._cancel.is_set():
                return True
            if self._pause.is_set():
                await asyncio.sleep(0.5)
                continue
            progress = elapsed / total_sec
            self._apply_work_lighting(progress)
            step = min(tick, total_sec - elapsed)
            await asyncio.sleep(step)
            elapsed += step

        self._apply_work_lighting(1.0)
        return False

    async def _run_break(self, is_long: bool) -> bool:
        minutes = self._config.long_break_min if is_long else self._config.short_break_min
        label = "long break" if is_long else "short break"
        print(f"[aether] FOCUS: {label} ({minutes}min)", file=sys.stderr)

        await self._flash_ropes(count=2)

        if is_long:
            self._apply_long_break_lighting()
        else:
            self._apply_break_lighting()

        cancelled = await self._wait_with_pause(minutes * 60)
        if cancelled:
            return True

        await self._flash_ropes(count=2)
        return False

    async def run(self) -> None:
        try:
            while True:
                if self.phase == PomodoroPhase.WORK:
                    cancelled = await self._run_work()
                    if cancelled:
                        return
                    done = self._advance()
                    if done:
                        return
                elif self.phase == PomodoroPhase.SHORT_BREAK:
                    cancelled = await self._run_break(is_long=False)
                    if cancelled:
                        return
                    done = self._advance()
                    if done:
                        return
                elif self.phase == PomodoroPhase.LONG_BREAK:
                    cancelled = await self._run_break(is_long=True)
                    if cancelled:
                        return
                    done = self._advance()
                    if done:
                        return
        finally:
            self._mixer.release_all("focus")
            self._mixer.resolve()
            print("[aether] FOCUS: ended", file=sys.stderr)
