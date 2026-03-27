from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


class GoveeAdapter:
    def __init__(self, mqtt_client, zones_config: dict, topic_prefix: str = "aether"):
        self._mqtt = mqtt_client
        self._zones = zones_config
        self._prefix = topic_prefix

    def publish_zone(self, zone: str, color: dict) -> None:
        zone_cfg = self._zones.get(zone)
        if zone_cfg is None or zone_cfg.govee_device is None:
            return
        topic = f"{self._prefix}/light/zone/{zone}"
        self._mqtt.publish(topic, json.dumps(color), retain=True)

    def publish_state(self, state: str) -> None:
        self._mqtt.publish(f"{self._prefix}/state", json.dumps(state), retain=True)

    def publish_transition(self, from_state: str, to_state: str, reason: str) -> None:
        payload = {
            "from": from_state,
            "to": to_state,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._mqtt.publish(f"{self._prefix}/state/transition", json.dumps(payload), retain=False)

    def publish_presence(self, human: bool) -> None:
        self._mqtt.publish(f"{self._prefix}/presence/human", json.dumps(human), retain=True)
        if human:
            self._mqtt.publish(
                f"{self._prefix}/presence/last_seen",
                json.dumps(datetime.now(timezone.utc).isoformat()),
                retain=True,
            )
