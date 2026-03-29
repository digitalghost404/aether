from __future__ import annotations

from enum import Enum


class Intent(Enum):
    MODE_FOCUS = "mode_focus"
    MODE_FOCUS_STOP = "mode_focus_stop"
    MODE_PARTY = "mode_party"
    MODE_PARTY_STOP = "mode_party_stop"
    MODE_SLEEP = "mode_sleep"
    MODE_STOP = "mode_stop"
    PAUSE = "pause"
    RESUME = "resume"
    BRIGHTNESS_UP = "brightness_up"
    BRIGHTNESS_DOWN = "brightness_down"
    COLOR_WARMER = "color_warmer"
    COLOR_COOLER = "color_cooler"
    LIGHTS_OFF = "lights_off"
    LIGHTS_ON = "lights_on"
    SCENE_SET = "scene_set"
    SCENE_RANDOM = "scene_random"
    SCENE_RESET = "scene_reset"
    SCENE_QUERY = "scene_query"


KEYWORD_TABLE: list[tuple[str, Intent]] = [
    ("stop focus", Intent.MODE_FOCUS_STOP),
    ("end focus", Intent.MODE_FOCUS_STOP),
    ("stop party", Intent.MODE_PARTY_STOP),
    ("party mode", Intent.MODE_PARTY),
    ("lights off", Intent.LIGHTS_OFF),
    ("lights on", Intent.LIGHTS_ON),
    ("goodnight", Intent.MODE_SLEEP),
    ("unpause", Intent.RESUME),
    ("brighter", Intent.BRIGHTNESS_UP),
    ("bright", Intent.BRIGHTNESS_UP),
    ("dimmer", Intent.BRIGHTNESS_DOWN),
    ("dim", Intent.BRIGHTNESS_DOWN),
    ("warmer", Intent.COLOR_WARMER),
    ("cooler", Intent.COLOR_COOLER),
    # Scene intents (before generic stop/cancel)
    ("set scene", Intent.SCENE_SET),
    ("switch to", Intent.SCENE_SET),
    ("random scene", Intent.SCENE_RANDOM),
    ("pick a scene", Intent.SCENE_RANDOM),
    ("go back to default", Intent.SCENE_RESET),
    ("what scene", Intent.SCENE_QUERY),
    ("current scene", Intent.SCENE_QUERY),
    ("normal", Intent.SCENE_RESET),
    ("reset", Intent.SCENE_RESET),
    # Generic mode controls (after scene-specific patterns)
    ("focus", Intent.MODE_FOCUS),
    ("party", Intent.MODE_PARTY),
    ("sleep", Intent.MODE_SLEEP),
    ("stop", Intent.MODE_STOP),
    ("cancel", Intent.MODE_STOP),
    ("pause", Intent.PAUSE),
    ("resume", Intent.RESUME),
]


def classify_intent(text: str) -> Intent | None:
    lower = text.lower().strip()
    for keyword, intent in KEYWORD_TABLE:
        if keyword in lower:
            return intent
    return None
