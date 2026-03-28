from __future__ import annotations

import time
from enum import Enum

from aether.config import GestureConfig


class Gesture(Enum):
    THUMBS_UP = "thumbs_up"
    THUMBS_DOWN = "thumbs_down"
    FIST = "fist"


THUMB_TIP = 4
THUMB_MCP = 2
INDEX_TIP = 8
INDEX_PIP = 6
MIDDLE_TIP = 12
MIDDLE_PIP = 10
RING_TIP = 16
RING_PIP = 14
PINKY_TIP = 20
PINKY_PIP = 18

FINGER_TIPS_AND_PIPS = [
    (INDEX_TIP, INDEX_PIP),
    (MIDDLE_TIP, MIDDLE_PIP),
    (RING_TIP, RING_PIP),
    (PINKY_TIP, PINKY_PIP),
]

_FIST_SPREAD_THRESHOLD = 0.05


class GestureClassifier:
    def __init__(self, config: GestureConfig):
        self._config = config
        self._consecutive_gesture: Gesture | None = None
        self._consecutive_count: int = 0
        self._cooldowns: dict[Gesture, float] = {}

    def _classify_landmarks(self, landmarks: list[tuple[float, float]]) -> Gesture | None:
        thumb_tip_y = landmarks[THUMB_TIP][1]
        thumb_mcp_y = landmarks[THUMB_MCP][1]

        fingers_curled = all(
            landmarks[tip][1] > landmarks[pip][1]
            for tip, pip in FINGER_TIPS_AND_PIPS
        )

        if not fingers_curled:
            return None

        thumb_up = thumb_tip_y < thumb_mcp_y
        thumb_down = thumb_tip_y > thumb_mcp_y

        if thumb_up:
            return Gesture.THUMBS_UP

        if thumb_down:
            # Distinguish FIST (thumb tucked alongside fingers, uniform spread)
            # from THUMBS_DOWN (thumb hanging down, fingers at natural x positions).
            # In a fist the finger tips form a compact, uniform cluster; in
            # thumbs-down the fingers fan out with their natural x-spread.
            tip_xs = [landmarks[tip][0] for tip, _ in FINGER_TIPS_AND_PIPS]
            x_spread = max(tip_xs) - min(tip_xs)
            if x_spread <= _FIST_SPREAD_THRESHOLD:
                return Gesture.FIST
            return Gesture.THUMBS_DOWN

        return None

    def update(self, landmarks: list[tuple[float, float]]) -> Gesture | None:
        gesture = self._classify_landmarks(landmarks)
        if gesture != self._consecutive_gesture:
            self._consecutive_gesture = gesture
            self._consecutive_count = 1 if gesture is not None else 0
        else:
            if gesture is None:
                return None
            self._consecutive_count += 1

        if gesture is None:
            return None

        required = (
            self._config.fist_hold_frames
            if gesture == Gesture.FIST
            else self._config.consecutive_frames
        )
        if self._consecutive_count < required:
            return None
        now = time.monotonic()
        last = self._cooldowns.get(gesture, 0.0)
        if now - last < self._config.cooldown_sec:
            return None
        self._cooldowns[gesture] = now
        self._consecutive_count = 0
        return gesture
