from __future__ import annotations

from aether.lighting.ramp import ColorState


class ZoneManager:
    ZONE_NAMES = ("wall_left", "wall_right", "monitor", "floor", "bedroom")

    def __init__(self, govee_adapter):
        self._adapter = govee_adapter
        self._current: dict[str, ColorState] = {
            name: ColorState(r=0, g=0, b=0, brightness=0) for name in self.ZONE_NAMES
        }
        self.paused: bool = False

    def get(self, zone: str) -> ColorState:
        return self._current[zone]

    def set_zone(self, zone: str, state: ColorState) -> None:
        if self._current[zone] == state:
            return  # Skip duplicate — avoid hammering Govee API
        self._current[zone] = state
        if not self.paused:
            self._adapter.publish_zone(zone, state.to_dict())

    def set_all(self, state: ColorState) -> None:
        for zone in self.ZONE_NAMES:
            self.set_zone(zone, state)

    def get_all(self) -> dict[str, ColorState]:
        return dict(self._current)

    def flush_current(self) -> None:
        """Re-publish all current zone states. Call after resume."""
        for zone, state in self._current.items():
            self._adapter.publish_zone(zone, state.to_dict())
