import json
from unittest.mock import MagicMock
from aether.adapters.govee import GoveeAdapter


def test_publish_zone_publishes_to_aether_and_govee():
    mqtt = MagicMock()
    zones_config = {
        "floor": MagicMock(govee_device="AABBCCDDEEFF"),
    }
    adapter = GoveeAdapter(mqtt, zones_config, topic_prefix="aether")
    adapter.publish_zone("floor", {"r": 255, "g": 180, "b": 0, "brightness": 100})
    assert mqtt.publish.call_count == 2
    # First call: aether status topic
    aether_call = mqtt.publish.call_args_list[0]
    assert aether_call[0][0] == "aether/light/zone/floor"
    # Second call: govee2mqtt command topic
    govee_call = mqtt.publish.call_args_list[1]
    assert govee_call[0][0] == "gv2mqtt/light/AABBCCDDEEFF/command"


def test_publish_zone_govee_payload_format():
    mqtt = MagicMock()
    zones_config = {
        "wall_left": MagicMock(govee_device="1122334455"),
    }
    adapter = GoveeAdapter(mqtt, zones_config, topic_prefix="aether")
    adapter.publish_zone("wall_left", {"r": 80, "g": 60, "b": 180, "brightness": 40})
    govee_call = mqtt.publish.call_args_list[1]
    payload = json.loads(govee_call[0][1])
    assert payload["state"] == "ON"
    assert payload["color"] == {"r": 80, "g": 60, "b": 180}
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
