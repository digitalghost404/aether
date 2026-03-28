from __future__ import annotations

import sys
from datetime import datetime, timezone

from aether.lighting.ramp import ColorState
from aether.state import Event, State, StateMachine
from aether.vox.intent import Intent


class VoxHandler:
    def __init__(self, state_machine: StateMachine, mixer, mqtt, config):
        self._sm = state_machine
        self._mixer = mixer
        self._mqtt = mqtt
        self._config = config

    def execute(self, intent: Intent, text: str) -> None:
        print(f"[aether] VOX: intent={intent.value} text={text!r}", file=sys.stderr)

        self._mqtt.publish("aether/vox/last_command", {
            "text": text,
            "intent": intent.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, retain=True)

        if intent == Intent.MODE_FOCUS and self._sm.state == State.PRESENT:
            self._sm.handle_event(Event.FOCUS_START)
        elif intent == Intent.MODE_FOCUS_STOP and self._sm.state == State.FOCUS:
            self._sm.handle_event(Event.FOCUS_STOP)
        elif intent == Intent.MODE_PARTY and self._sm.state == State.PRESENT:
            self._sm.handle_event(Event.PARTY_START)
        elif intent == Intent.MODE_PARTY_STOP and self._sm.state == State.PARTY:
            self._sm.handle_event(Event.PARTY_STOP)
        elif intent == Intent.MODE_SLEEP and self._sm.state == State.PRESENT:
            self._sm.handle_event(Event.SLEEP_START)
        elif intent == Intent.MODE_STOP:
            self._stop_current_mode()
        elif intent == Intent.PAUSE:
            self._mqtt.publish(f"{self._config.mqtt.topic_prefix}/control", "pause")
        elif intent == Intent.RESUME:
            self._mqtt.publish(f"{self._config.mqtt.topic_prefix}/control", "resume")
        elif intent == Intent.BRIGHTNESS_UP:
            self._adjust_brightness(20)
        elif intent == Intent.BRIGHTNESS_DOWN:
            self._adjust_brightness(-20)
        elif intent == Intent.COLOR_WARMER:
            self._shift_color_temp(warm=True)
        elif intent == Intent.COLOR_COOLER:
            self._shift_color_temp(warm=False)
        elif intent == Intent.LIGHTS_OFF:
            off = ColorState(r=0, g=0, b=0, brightness=0)
            ttl = self._config.mixer.manual_ttl_sec
            self._mixer.submit_all("voice", off, priority=0, ttl_sec=ttl)
            self._mixer.resolve()
        elif intent == Intent.LIGHTS_ON:
            self._mixer.release_all("voice")
            self._mixer.resolve()

    def _stop_current_mode(self) -> None:
        if self._sm.state == State.FOCUS:
            self._sm.handle_event(Event.FOCUS_STOP)
        elif self._sm.state == State.PARTY:
            self._sm.handle_event(Event.PARTY_STOP)
        elif self._sm.state == State.SLEEP:
            self._sm.handle_event(Event.SLEEP_CANCEL)

    def _adjust_brightness(self, delta: int) -> None:
        ttl = self._config.mixer.manual_ttl_sec
        claims = self._mixer.get_active_claims()
        for zone, claim in claims.items():
            current_br = claim.color.brightness
            new_br = max(0, min(100, current_br + delta))
            new_color = ColorState(
                r=claim.color.r, g=claim.color.g, b=claim.color.b,
                brightness=new_br,
            )
            self._mixer.submit("voice", zone, new_color, priority=0, ttl_sec=ttl)
        self._mixer.resolve()

    def _shift_color_temp(self, warm: bool) -> None:
        ttl = self._config.mixer.manual_ttl_sec
        claims = self._mixer.get_active_claims()
        for zone, claim in claims.items():
            r, g, b = claim.color.r, claim.color.g, claim.color.b
            if warm:
                r = min(255, r + 30)
                b = max(0, b - 30)
            else:
                r = max(0, r - 30)
                b = min(255, b + 30)
            new_color = ColorState(r=r, g=g, b=b, brightness=claim.color.brightness)
            self._mixer.submit("voice", zone, new_color, priority=0, ttl_sec=ttl)
        self._mixer.resolve()
