import json
from unittest.mock import MagicMock, patch, PropertyMock
from aether.adapters.openrgb import OpenRGBAdapter


def _make_fake_device(name: str):
    device = MagicMock()
    device.name = name
    device.modes = [MagicMock(name="Direct", id=0)]
    return device


def _make_fake_client(devices: list):
    client = MagicMock()
    client.devices = devices
    client.ee = MagicMock()
    return client


def test_publish_zone_sets_color_on_devices():
    dev1 = _make_fake_device("SteelSeries Apex 3 TKL")
    dev2 = _make_fake_device("SteelSeries Rival 600")
    client = _make_fake_client([dev1, dev2])
    mqtt = MagicMock()

    zones_config = {
        "desk": MagicMock(openrgb_devices=["SteelSeries Apex 3 TKL", "SteelSeries Rival 600"]),
    }

    with patch("aether.adapters.openrgb.OpenRGBClient", return_value=client):
        adapter = OpenRGBAdapter(mqtt, zones_config)
        adapter.connect()
        adapter.publish_zone("desk", {"r": 255, "g": 223, "b": 191, "brightness": 80})

    # Brightness 80% of (255, 223, 191) = (204, 178, 152)
    for dev in [dev1, dev2]:
        dev.set_color.assert_called_once()
        color_arg = dev.set_color.call_args[0][0]
        assert color_arg.red == 204
        assert color_arg.green == 178
        assert color_arg.blue == 152


def test_publish_zone_publishes_mqtt_status():
    dev1 = _make_fake_device("Keyboard")
    client = _make_fake_client([dev1])
    mqtt = MagicMock()

    zones_config = {
        "desk": MagicMock(openrgb_devices=["Keyboard"]),
    }

    with patch("aether.adapters.openrgb.OpenRGBClient", return_value=client):
        adapter = OpenRGBAdapter(mqtt, zones_config, topic_prefix="aether")
        adapter.connect()
        mqtt.publish.reset_mock()  # clear connect() status publishes
        adapter.publish_zone("desk", {"r": 255, "g": 0, "b": 0, "brightness": 100})

    mqtt.publish.assert_called_once()
    topic = mqtt.publish.call_args[0][0]
    assert topic == "aether/peripheral/zone/desk"


def test_publish_zone_skips_unconfigured_zone():
    client = _make_fake_client([])
    mqtt = MagicMock()
    zones_config = {}

    with patch("aether.adapters.openrgb.OpenRGBClient", return_value=client):
        adapter = OpenRGBAdapter(mqtt, zones_config)
        adapter.connect()
        mqtt.publish.reset_mock()
        adapter.publish_zone("desk", {"r": 255, "g": 0, "b": 0, "brightness": 100})

    mqtt.publish.assert_not_called()


def test_publish_zone_skips_missing_device():
    client = _make_fake_client([])  # no devices on server
    mqtt = MagicMock()

    zones_config = {
        "desk": MagicMock(openrgb_devices=["Missing Device"]),
    }

    with patch("aether.adapters.openrgb.OpenRGBClient", return_value=client):
        adapter = OpenRGBAdapter(mqtt, zones_config)
        adapter.connect()
        mqtt.publish.reset_mock()
        adapter.publish_zone("desk", {"r": 255, "g": 0, "b": 0, "brightness": 100})
    # Should not raise, no devices matched so no set_color and no MQTT
    mqtt.publish.assert_not_called()


def test_brightness_zero_sends_black():
    dev = _make_fake_device("Keyboard")
    client = _make_fake_client([dev])
    mqtt = MagicMock()

    zones_config = {
        "desk": MagicMock(openrgb_devices=["Keyboard"]),
    }

    with patch("aether.adapters.openrgb.OpenRGBClient", return_value=client):
        adapter = OpenRGBAdapter(mqtt, zones_config)
        adapter.connect()
        adapter.publish_zone("desk", {"r": 255, "g": 128, "b": 64, "brightness": 0})

    color_arg = dev.set_color.call_args[0][0]
    assert color_arg.red == 0
    assert color_arg.green == 0
    assert color_arg.blue == 0


def test_disconnect_not_connected():
    mqtt = MagicMock()
    adapter = OpenRGBAdapter(mqtt, {})
    adapter.disconnect()  # should not raise


def test_status_connected():
    dev = _make_fake_device("Keyboard")
    client = _make_fake_client([dev])
    mqtt = MagicMock()

    zones_config = {
        "desk": MagicMock(openrgb_devices=["Keyboard"]),
    }

    with patch("aether.adapters.openrgb.OpenRGBClient", return_value=client):
        adapter = OpenRGBAdapter(mqtt, zones_config, topic_prefix="aether")
        adapter.connect()

    status_calls = [c for c in mqtt.publish.call_args_list if "peripheral/status" in str(c)]
    assert len(status_calls) >= 1


def test_status_degraded_when_device_missing():
    client = _make_fake_client([])  # server has no devices
    mqtt = MagicMock()

    zones_config = {
        "desk": MagicMock(openrgb_devices=["Missing Keyboard"]),
    }

    with patch("aether.adapters.openrgb.OpenRGBClient", return_value=client):
        adapter = OpenRGBAdapter(mqtt, zones_config, topic_prefix="aether")
        adapter.connect()

    status_calls = [c for c in mqtt.publish.call_args_list if "peripheral/status" in str(c)]
    assert any('"degraded"' in str(c) for c in status_calls)
