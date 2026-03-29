from unittest.mock import MagicMock
from aether.lighting.ramp import ColorState
from aether.lighting.zones import ZoneManager, ZONE_NAMES


def test_zone_names_includes_desk_and_tower():
    assert "desk" in ZONE_NAMES
    assert "tower" in ZONE_NAMES
    assert len(ZONE_NAMES) == 7


def test_zone_manager_routes_to_correct_adapter():
    govee = MagicMock()
    openrgb = MagicMock()
    adapters = {
        "wall_left": govee, "wall_right": govee, "monitor": govee,
        "floor": govee, "bedroom": govee, "desk": openrgb, "tower": openrgb,
    }
    zm = ZoneManager(adapters)
    red = ColorState(r=255, g=0, b=0, brightness=100)
    zm.set_zone("floor", red)
    govee.publish_zone.assert_called_once_with("floor", red.to_dict())
    openrgb.publish_zone.assert_not_called()


def test_zone_manager_routes_openrgb_zone():
    govee = MagicMock()
    openrgb = MagicMock()
    adapters = {
        "wall_left": govee, "wall_right": govee, "monitor": govee,
        "floor": govee, "bedroom": govee, "desk": openrgb, "tower": openrgb,
    }
    zm = ZoneManager(adapters)
    blue = ColorState(r=0, g=0, b=255, brightness=80)
    zm.set_zone("desk", blue)
    openrgb.publish_zone.assert_called_once_with("desk", blue.to_dict())
    govee.publish_zone.assert_not_called()


def test_set_all_covers_all_7_zones():
    adapter = MagicMock()
    adapters = {name: adapter for name in ZONE_NAMES}
    zm = ZoneManager(adapters)
    white = ColorState(r=255, g=255, b=255, brightness=100)
    zm.set_all(white)
    assert adapter.publish_zone.call_count == 7


def test_dedup_skips_unchanged():
    adapter = MagicMock()
    adapters = {"floor": adapter}
    zm = ZoneManager(adapters)
    red = ColorState(r=255, g=0, b=0, brightness=100)
    zm.set_zone("floor", red)
    zm.set_zone("floor", red)
    assert adapter.publish_zone.call_count == 1


def test_flush_current_republishes_all():
    adapter = MagicMock()
    adapters = {name: adapter for name in ZONE_NAMES}
    zm = ZoneManager(adapters)
    red = ColorState(r=255, g=0, b=0, brightness=100)
    zm.set_zone("floor", red)
    adapter.publish_zone.reset_mock()
    zm.flush_current()
    assert adapter.publish_zone.call_count == 7


def test_paused_skips_publish():
    adapter = MagicMock()
    adapters = {"floor": adapter}
    zm = ZoneManager(adapters)
    zm.paused = True
    red = ColorState(r=255, g=0, b=0, brightness=100)
    zm.set_zone("floor", red)
    adapter.publish_zone.assert_not_called()


def test_zone_without_adapter_is_skipped():
    adapters = {"floor": MagicMock()}
    zm = ZoneManager(adapters)
    blue = ColorState(r=0, g=0, b=255, brightness=100)
    zm.set_zone("desk", blue)  # should not raise
