from aether.lighting.zones import ZoneManager
from aether.lighting.ramp import ColorState


class FakeAdapter:
    def __init__(self):
        self.published = []

    def publish_zone(self, zone: str, color: dict):
        self.published.append((zone, color))


def test_set_zone_publishes_when_not_paused():
    adapter = FakeAdapter()
    zm = ZoneManager({"floor": adapter})
    color = ColorState(r=255, g=0, b=0, brightness=100)
    zm.set_zone("floor", color)
    assert len(adapter.published) == 1
    assert adapter.published[0] == ("floor", color.to_dict())


def test_set_zone_suppressed_when_paused():
    adapter = FakeAdapter()
    zm = ZoneManager({"floor": adapter})
    zm.paused = True
    color = ColorState(r=255, g=0, b=0, brightness=100)
    zm.set_zone("floor", color)
    assert len(adapter.published) == 0


def test_resume_does_not_replay_suppressed():
    adapter = FakeAdapter()
    zm = ZoneManager({"floor": adapter})
    zm.paused = True
    color = ColorState(r=255, g=0, b=0, brightness=100)
    zm.set_zone("floor", color)
    zm.paused = False
    # No automatic replay — caller is responsible for re-applying state
    assert len(adapter.published) == 0


def test_current_state_tracks_even_when_paused():
    adapter = FakeAdapter()
    zm = ZoneManager({"floor": adapter})
    zm.paused = True
    color = ColorState(r=255, g=0, b=0, brightness=100)
    zm.set_zone("floor", color)
    # Internal state still updated for resume logic
    assert zm.get("floor") == color
