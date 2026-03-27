from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

import paho.mqtt.client as paho_mqtt


class MqttClient:
    def __init__(self, broker: str = "localhost", port: int = 1883):
        self._broker = broker
        self._port = port
        self._client = paho_mqtt.Client(paho_mqtt.CallbackAPIVersion.VERSION2)
        self._connected = False
        self._buffer: list[tuple[str, str, bool]] = []
        self._max_buffer = 10

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            self._connected = True
            print(f"[aether] MQTT connected to {self._broker}:{self._port}", file=sys.stderr)
            self._flush_buffer()
        else:
            print(f"[aether] MQTT connection failed: rc={rc}", file=sys.stderr)

    def _on_disconnect(self, client, userdata, flags, rc, properties=None):
        self._connected = False
        print(f"[aether] MQTT disconnected: rc={rc}", file=sys.stderr)

    def _flush_buffer(self):
        for topic, payload, retain in self._buffer:
            self._client.publish(topic, payload, qos=1, retain=retain)
        self._buffer.clear()

    def publish(self, topic: str, payload: Any, retain: bool = False) -> None:
        if isinstance(payload, (dict, list)):
            payload = json.dumps(payload)
        elif not isinstance(payload, str):
            payload = json.dumps(payload)

        if self._connected:
            self._client.publish(topic, payload, qos=1, retain=retain)
        else:
            if len(self._buffer) >= self._max_buffer:
                self._buffer.pop(0)
            self._buffer.append((topic, payload, retain))

    async def run(self) -> None:
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect

        while True:
            try:
                self._client.connect(self._broker, self._port)
                self._client.loop_start()
                while True:
                    await asyncio.sleep(1)
            except Exception as e:
                print(f"[aether] MQTT error: {e}. Retrying in 5s...", file=sys.stderr)
                self._connected = False
                await asyncio.sleep(5)

    def disconnect(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()
