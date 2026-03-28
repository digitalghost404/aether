from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from aether.lighting.ramp import ColorState
from aether.lighting.zones import ZoneManager


@dataclass
class Claim:
    source: str
    zone: str
    color: ColorState
    priority: int
    ttl_sec: float | None = None
    created_at: float = field(default_factory=time.monotonic)


class Mixer:
    def __init__(self, zones: ZoneManager):
        self._zones = zones
        self._claims: dict[str, dict[str, Claim]] = {}
        self._last_resolved: dict[str, ColorState] = {}

    def submit(self, source: str, zone: str, color: ColorState, priority: int, ttl_sec: float | None = None) -> None:
        if zone not in self._claims:
            self._claims[zone] = {}
        self._claims[zone][source] = Claim(
            source=source, zone=zone, color=color, priority=priority,
            ttl_sec=ttl_sec, created_at=time.monotonic(),
        )

    def submit_all(self, source: str, color: ColorState, priority: int, ttl_sec: float | None = None) -> None:
        for zone in ZoneManager.ZONE_NAMES:
            self.submit(source, zone, color, priority, ttl_sec)

    def release(self, source: str, zone: str) -> None:
        if zone in self._claims:
            self._claims[zone].pop(source, None)

    def release_all(self, source: str) -> None:
        for zone in list(self._claims):
            self._claims[zone].pop(source, None)

    def expire_claims(self) -> None:
        now = time.monotonic()
        for zone in list(self._claims):
            for source in list(self._claims[zone]):
                claim = self._claims[zone][source]
                if claim.ttl_sec is not None:
                    if now - claim.created_at >= claim.ttl_sec:
                        del self._claims[zone][source]

    def _resolve_zone(self, zone: str) -> ColorState | None:
        claims = self._claims.get(zone, {})
        if not claims:
            return None
        winner = min(claims.values(), key=lambda c: (c.priority, -c.created_at))
        return winner.color

    def resolve(self) -> None:
        if self._zones.paused:
            return
        for zone in ZoneManager.ZONE_NAMES:
            color = self._resolve_zone(zone)
            if color is not None:
                if self._last_resolved.get(zone) != color:
                    self._last_resolved[zone] = color
                    self._zones.set_zone(zone, color)

    def get_active_claims(self) -> dict[str, Claim]:
        result = {}
        for zone in ZoneManager.ZONE_NAMES:
            claims = self._claims.get(zone, {})
            if claims:
                winner = min(claims.values(), key=lambda c: (c.priority, -c.created_at))
                result[zone] = winner
        return result

    async def run(self, tick_interval: float = 1.0) -> None:
        while True:
            self.expire_claims()
            self.resolve()
            await asyncio.sleep(tick_interval)
