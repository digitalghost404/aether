from __future__ import annotations

import asyncio
import json
import sys
import uuid
from collections import defaultdict

import httpx


API_URL = "https://openapi.api.govee.com/router/api/v1/device/control"


class GoveeSegmentAdapter:
    def __init__(self, api_key: str, rate_limit: float = 0.15):
        self._api_key = api_key
        self._rate_limit = rate_limit
        self._client = httpx.AsyncClient(
            headers={
                "Govee-API-Key": api_key,
                "Content-Type": "application/json",
            },
            timeout=10,
        )
        self._last_request_time: float = 0

    async def _rate_wait(self) -> None:
        if self._rate_limit <= 0:
            return
        now = asyncio.get_event_loop().time()
        elapsed = now - self._last_request_time
        if elapsed < self._rate_limit:
            await asyncio.sleep(self._rate_limit - elapsed)
        self._last_request_time = asyncio.get_event_loop().time()

    async def _send(self, device_id: str, sku: str, capability: dict) -> None:
        payload = {
            "requestId": str(uuid.uuid4()),
            "payload": {
                "sku": sku,
                "device": device_id,
                "capability": capability,
            },
        }
        try:
            await self._rate_wait()
            resp = await self._client.post(API_URL, content=json.dumps(payload))
            if resp.status_code != 200:
                print(
                    f"[aether] Govee API error {resp.status_code}: {resp.text}",
                    file=sys.stderr,
                )
        except Exception as e:
            print(f"[aether] Govee API request failed: {e}", file=sys.stderr)

    @staticmethod
    def _encode_rgb(r: int, g: int, b: int) -> int:
        return (r << 16) | (g << 8) | b

    async def set_segments(
        self,
        device_id: str,
        sku: str,
        segments: dict[int, tuple[int, int, int]],
        brightness: int,
    ) -> None:
        color_groups: dict[tuple[int, int, int], list[int]] = defaultdict(list)
        for seg_idx, rgb in segments.items():
            color_groups[rgb].append(seg_idx)

        for rgb, seg_indices in color_groups.items():
            seg_indices.sort()
            await self._send(device_id, sku, {
                "type": "devices.capabilities.segment_color_setting",
                "instance": "segmentedColorRgb",
                "value": {
                    "segment": seg_indices,
                    "rgb": self._encode_rgb(*rgb),
                },
            })

    async def set_color(
        self,
        device_id: str,
        sku: str,
        color: tuple[int, int, int],
        brightness: int,
    ) -> None:
        await self._send(device_id, sku, {
            "type": "devices.capabilities.color_setting",
            "instance": "colorRgb",
            "value": self._encode_rgb(*color),
        })

    async def set_brightness(
        self,
        device_id: str,
        sku: str,
        brightness: int,
    ) -> None:
        await self._send(device_id, sku, {
            "type": "devices.capabilities.range",
            "instance": "brightness",
            "value": brightness,
        })

    async def close(self) -> None:
        await self._client.aclose()
