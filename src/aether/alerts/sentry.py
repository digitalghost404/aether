from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone


class SentryAlert:
    """Fires alerts when humans are detected in AWAY state."""

    def __init__(self, adapter, floor_zone_name: str, flash_color: list[int], flash_count: int):
        self._adapter = adapter
        self._floor_zone = floor_zone_name
        self._flash_color = flash_color
        self._flash_count = flash_count
        self._cooldown_sec = 30.0
        self._last_alert: float = 0.0

    async def trigger(self) -> None:
        import time
        now = time.monotonic()
        if now - self._last_alert < self._cooldown_sec:
            return
        self._last_alert = now

        timestamp = datetime.now(timezone.utc).isoformat()
        print(f"[aether] ALERT: Human detected while AWAY at {timestamp}", file=sys.stderr)

        self._adapter._mqtt.publish(
            "aether/alert/sentry",
            {"type": "human_detected", "timestamp": timestamp},
        )

        for _ in range(self._flash_count):
            self._adapter.publish_zone(
                self._floor_zone,
                {"r": self._flash_color[0], "g": self._flash_color[1], "b": self._flash_color[2], "brightness": 100},
            )
            await asyncio.sleep(0.5)
            self._adapter.publish_zone(
                self._floor_zone,
                {"r": 0, "g": 0, "b": 0, "brightness": 0},
            )
            await asyncio.sleep(0.5)
