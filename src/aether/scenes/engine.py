from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING

from aether.config import AetherConfig, SceneZoneConfig
from aether.lighting.ramp import ColorState
from aether.scenes.interpolate import interpolate_stops


def _to_platform_id(device_id: str) -> str:
    """Convert stripped device ID (10BDC9F082864183) to colon format (10:BD:C9:F0:82:86:41:83)."""
    if ":" in device_id:
        return device_id
    return ":".join(device_id[i:i+2] for i in range(0, len(device_id), 2))


def _quantize_segments(
    segments: dict[int, tuple[int, int, int]], step: int = 16
) -> dict[int, tuple[int, int, int]]:
    """Round RGB values to nearest step to increase color batching.

    A 22-segment gradient with step=8 typically reduces from 22 unique colors
    to 5-8, cutting API calls by ~70%.
    """
    return {
        idx: (
            min(255, round(r / step) * step),
            min(255, round(g / step) * step),
            min(255, round(b / step) * step),
        )
        for idx, (r, g, b) in segments.items()
    }

if TYPE_CHECKING:
    from aether.adapters.govee_segment import GoveeSegmentAdapter
    from aether.mixer import Mixer


DEFAULT_SEGMENT_COUNTS = {
    "wall_left": 22,
    "wall_right": 22,
    "monitor": 15,
    "floor": 7,
    "bedroom": 1,
}

ZONE_SKUS = {
    "wall_left": "H6641",
    "wall_right": "H6641",
    "monitor": "H6168",
    "floor": "H6076",
    "bedroom": "H6022",
}


class SceneEngine:
    def __init__(
        self,
        config: AetherConfig,
        segment_adapter,
        mixer,
        mqtt,
        segment_counts: dict[str, int] | None = None,
    ):
        self._config = config
        self._segment_adapter = segment_adapter
        self._mixer = mixer
        self._mqtt = mqtt
        self._segment_counts = segment_counts or DEFAULT_SEGMENT_COUNTS
        self._scenes = config.scenes
        self._phase_scenes = config.circadian.phase_scenes
        self._active_scene: str | None = None
        self._manual_override: bool = False

    @property
    def active_scene(self) -> str | None:
        return self._active_scene

    def get_scene_names(self) -> list[str]:
        return list(self._scenes.keys())

    def reset_to_circadian(self) -> None:
        self._manual_override = False
        self._mqtt.publish("aether/scene/mode", json.dumps("circadian"), retain=True)

    def invalidate(self) -> None:
        """Clear cached active scene so the next circadian tick re-applies."""
        self._active_scene = None

    async def apply_scene(self, name: str, *, manual: bool = False) -> None:
        if name not in self._scenes:
            print(f"[aether] Scene '{name}' not found, ignoring", file=sys.stderr)
            return

        import asyncio

        scene_zones = self._scenes[name]
        zones_config = self._config.zones

        for zone_name, zone_scene in scene_zones.items():
            zone_cfg = zones_config.get(zone_name)

            if zone_cfg is not None and zone_cfg.govee_device is not None:
                device_id = _to_platform_id(zone_cfg.govee_device)
                sku = ZONE_SKUS.get(zone_name, "H6641")

                # Set brightness first (one call)
                await self._segment_adapter.set_brightness(
                    device_id, sku, zone_scene.brightness
                )

                if zone_scene.stops is not None:
                    # Enable gradient mode for segmented colors
                    await self._segment_adapter.set_gradient_toggle(device_id, sku, on=True)
                    seg_count = self._segment_counts.get(zone_name, 1)
                    segments = _quantize_segments(interpolate_stops(zone_scene.stops, seg_count))
                    await self._segment_adapter.set_segments(
                        device_id, sku, segments, zone_scene.brightness
                    )
                elif zone_scene.color is not None:
                    color = tuple(zone_scene.color)
                    await self._segment_adapter.set_color(
                        device_id, sku, color, zone_scene.brightness
                    )

            elif zone_cfg is not None and zone_cfg.openrgb_devices:
                if zone_scene.color is not None:
                    color = ColorState(
                        r=zone_scene.color[0],
                        g=zone_scene.color[1],
                        b=zone_scene.color[2],
                        brightness=zone_scene.brightness,
                    )
                    self._mixer.submit("scene", zone_name, color, priority=2)

        self._mixer.resolve()

        self._active_scene = name
        if manual:
            self._manual_override = True

        self._mqtt.publish("aether/scene/active", json.dumps(name), retain=True)
        mode = "manual" if self._manual_override else "circadian"
        self._mqtt.publish("aether/scene/mode", json.dumps(mode), retain=True)

    async def apply_circadian_scene(self, phase: str) -> None:
        if self._manual_override:
            return

        scene_name = self._phase_scenes.get(phase)
        if scene_name is None:
            return

        if scene_name == self._active_scene:
            return

        await self.apply_scene(scene_name, manual=False)
