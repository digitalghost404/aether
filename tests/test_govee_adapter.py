import json
from unittest.mock import MagicMock
from aether.adapters.govee import GoveeAdapter


def test_publish_zone_formats_topic():
    mqtt = MagicMock()
    zones_config = {
        "floor": MagicMock(govee_device="AA:BB:CC:DD:EE:FF"),
    }
    adapter = GoveeAdapter(mqtt, zones_config, topic_prefix="aether")
    adapter.publish_zone("floor", {"r": 255, "g": 180, "b": 0, "brightness": 100})
    mqtt.publish.assert_called_once()
    call_args = mqtt.publish.call_args
    assert call_args[0][0] == "aether/light/zone/floor"


def test_publish_zone_payload_is_json():
    mqtt = MagicMock()
    zones_config = {
        "wall_left": MagicMock(govee_device="11:22:33:44:55:66"),
    }
    adapter = GoveeAdapter(mqtt, zones_config, topic_prefix="aether")
    adapter.publish_zone("wall_left", {"r": 80, "g": 60, "b": 180, "brightness": 40})
    call_args = mqtt.publish.call_args
    payload = json.loads(call_args[0][1])
    assert payload["r"] == 80
    assert payload["g"] == 60
    assert payload["b"] == 180
    assert payload["brightness"] == 40


def test_publish_zone_skips_unconfigured():
    mqtt = MagicMock()
    zones_config = {
        "floor": MagicMock(govee_device=None),
    }
    adapter = GoveeAdapter(mqtt, zones_config, topic_prefix="aether")
    adapter.publish_zone("floor", {"r": 255, "g": 0, "b": 0, "brightness": 100})
    mqtt.publish.assert_not_called()


def test_publish_state():
    mqtt = MagicMock()
    adapter = GoveeAdapter(mqtt, {}, topic_prefix="aether")
    adapter.publish_state("away")
    mqtt.publish.assert_called_once_with("aether/state", '"away"', retain=True)


def test_publish_transition():
    mqtt = MagicMock()
    adapter = GoveeAdapter(mqtt, {}, topic_prefix="aether")
    adapter.publish_transition("present", "away", "human_absent")
    call_args = mqtt.publish.call_args
    assert call_args[0][0] == "aether/state/transition"
    payload = json.loads(call_args[0][1])
    assert payload["from"] == "present"
    assert payload["to"] == "away"
    assert payload["reason"] == "human_absent"
