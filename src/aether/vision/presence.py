from __future__ import annotations

import sys
import time

import mediapipe as mp
import numpy as np

from aether.state import Event, State, StateMachine


class PresenceTracker:
    """Tracks human presence and emits state machine events."""

    def __init__(self, absence_timeout_sec: int, state_machine: StateMachine):
        self._timeout = absence_timeout_sec
        self._sm = state_machine
        self._last_human_seen: float = time.monotonic()
        self._absence_fired: bool = False

    def update(self, human_detected: bool, now: float | None = None) -> None:
        now = now if now is not None else time.monotonic()

        if human_detected:
            self._last_human_seen = now
            self._absence_fired = False

            if self._sm.state == State.AWAY:
                self._sm.handle_event(Event.HUMAN_DETECTED)
        else:
            elapsed = now - self._last_human_seen
            if elapsed >= self._timeout and not self._absence_fired:
                self._absence_fired = True
                self._sm.handle_event(Event.HUMAN_ABSENT)


class PresenceDetector:
    """Runs MediaPipe pose on frames and feeds PresenceTracker."""

    def __init__(self, presence_config, state_machine: StateMachine):
        self._tracker = PresenceTracker(
            absence_timeout_sec=presence_config.absence_timeout_sec,
            state_machine=state_machine,
        )
        self._pose = mp.solutions.pose.Pose(
            static_image_mode=False,
            model_complexity=0,
            min_detection_confidence=presence_config.detection_confidence,
        )

    def process_frame(self, frame: np.ndarray) -> None:
        rgb = frame[:, :, ::-1]  # BGR -> RGB
        result = self._pose.process(rgb)
        human_detected = result.pose_landmarks is not None
        self._tracker.update(human_detected)

    @property
    def tracker(self) -> PresenceTracker:
        return self._tracker
