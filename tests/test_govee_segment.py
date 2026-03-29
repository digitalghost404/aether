import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx

from aether.adapters.govee_segment import GoveeSegmentAdapter


@pytest.fixture
def adapter():
    return GoveeSegmentAdapter(api_key="test-api-key", rate_limit=0.0)


@pytest.mark.asyncio
async def test_set_segments_groups_by_color(adapter):
    mock_response = httpx.Response(200, json={"code": 200, "message": "success"})

    with patch.object(adapter._client, "post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
        segments = {
            0: (255, 0, 0),
            1: (255, 0, 0),
            2: (255, 0, 0),
            3: (0, 255, 0),
            4: (0, 255, 0),
        }
        await adapter.set_segments("10:BD:C9:F0:82:86:41:83", "H6641", segments, brightness=70)
        assert mock_post.call_count == 2

        calls = mock_post.call_args_list
        all_segments = []
        for call in calls:
            content = json.loads(call.kwargs.get("content", "{}"))
            cap = content["payload"]["capability"]
            assert cap["type"] == "devices.capabilities.segment_color_setting"
            assert cap["instance"] == "segmentedColorRgb"
            all_segments.extend(cap["value"]["segment"])
        assert sorted(all_segments) == [0, 1, 2, 3, 4]


@pytest.mark.asyncio
async def test_rgb_encoding(adapter):
    mock_response = httpx.Response(200, json={"code": 200, "message": "success"})

    with patch.object(adapter._client, "post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
        await adapter.set_segments("10:BD:C9:F0:82:86:41:83", "H6641", {0: (255, 128, 0)}, brightness=70)
        call_content = json.loads(mock_post.call_args.kwargs.get("content", "{}"))
        rgb_value = call_content["payload"]["capability"]["value"]["rgb"]
        assert rgb_value == (255 << 16) | (128 << 8) | 0


@pytest.mark.asyncio
async def test_set_color_single_device(adapter):
    mock_response = httpx.Response(200, json={"code": 200, "message": "success"})

    with patch.object(adapter._client, "post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
        await adapter.set_color("AA:BB:CC:DD:EE:FF:00:11", "H6022", (180, 140, 60), brightness=60)
        assert mock_post.call_count == 1
        call_content = json.loads(mock_post.call_args.kwargs.get("content", "{}"))
        cap = call_content["payload"]["capability"]
        assert cap["instance"] == "colorRgb"
        assert cap["value"] == (180 << 16) | (140 << 8) | 60


@pytest.mark.asyncio
async def test_set_brightness(adapter):
    mock_response = httpx.Response(200, json={"code": 200, "message": "success"})

    with patch.object(adapter._client, "post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
        await adapter.set_brightness("AA:BB:CC:DD:EE:FF:00:11", "H6641", 80)
        call_content = json.loads(mock_post.call_args.kwargs.get("content", "{}"))
        cap = call_content["payload"]["capability"]
        assert cap["type"] == "devices.capabilities.range"
        assert cap["instance"] == "brightness"
        assert cap["value"] == 80


@pytest.mark.asyncio
async def test_api_key_in_header(adapter):
    mock_response = httpx.Response(200, json={"code": 200, "message": "success"})

    with patch.object(adapter._client, "post", new_callable=AsyncMock, return_value=mock_response):
        await adapter.set_color("AA:BB:CC:DD:EE:FF:00:11", "H6022", (255, 0, 0), brightness=100)
        assert adapter._client.headers.get("Govee-API-Key") == "test-api-key"


@pytest.mark.asyncio
async def test_api_error_logged_not_raised(adapter):
    mock_response = httpx.Response(429, json={"code": 429, "message": "rate limited"})

    with patch.object(adapter._client, "post", new_callable=AsyncMock, return_value=mock_response):
        await adapter.set_segments("10:BD:C9:F0:82:86:41:83", "H6641", {0: (255, 0, 0)}, brightness=70)
