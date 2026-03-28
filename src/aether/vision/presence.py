from __future__ import annotations

import sys
import time

import mediapipe as mp
from mediapipe.tasks.python import BaseOptions, vision
import numpy as np

from aether.state import Event, State, StateMachine

POSE_MODEL_PATH = str(
    __import__("pathlib").Path.home() / ".cache" / "aether" / "pose_landmarker_lite.task"
)


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
            if self._sm.state in (State.FOCUS, State.PARTY):
                return
            elapsed = now - self._last_human_seen
            if elapsed >= self._timeout and not self._absence_fired:
                self._absence_fired = True
                self._sm.handle_event(Event.HUMAN_ABSENT)


class PresenceDetector:
    """Runs MediaPipe pose on frames and feeds PresenceTracker."""

    def __init__(self, presence_config, state_machine: StateMachine, gesture_callback=None):
        self._tracker = PresenceTracker(
            absence_timeout_sec=presence_config.absence_timeout_sec,
            state_machine=state_machine,
        )
        options = vision.PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=POSE_MODEL_PATH),
            running_mode=vision.RunningMode.IMAGE,
            min_pose_detection_confidence=presence_config.detection_confidence,
        )
        self._landmarker = vision.PoseLandmarker.create_from_options(options)
        self._gesture_callback = gesture_callback
        self._hand_landmarker = None

        if gesture_callback is not None:
            hand_model_path = str(
                __import__("pathlib").Path.home() / ".cache" / "aether" / "hand_landmarker.task"
            )
            try:
                hand_options = vision.HandLandmarkerOptions(
                    base_options=BaseOptions(model_asset_path=hand_model_path),
                    running_mode=vision.RunningMode.IMAGE,
                    min_hand_detection_confidence=0.5,
                    num_hands=1,
                )
                self._hand_landmarker = vision.HandLandmarker.create_from_options(hand_options)
                print("[aether] Gesture: hand landmarker loaded", file=sys.stderr)
            except Exception as e:
                print(f"[aether] Gesture: hand landmarker failed: {e}", file=sys.stderr)

    def process_frame(self, frame: np.ndarray) -> None:
        rgb = frame[:, :, ::-1]  # BGR -> RGB
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb.copy())
        result = self._landmarker.detect(mp_image)
        human_detected = len(result.pose_landmarks) > 0
        self._tracker.update(human_detected)

        if self._hand_landmarker is not None and self._gesture_callback is not None:
            try:
                hand_result = self._hand_landmarker.detect(mp_image)
                if hand_result.hand_landmarks:
                    landmarks = [(lm.x, lm.y) for lm in hand_result.hand_landmarks[0]]
                    self._gesture_callback(landmarks)
            except Exception:
                pass

    @property
    def tracker(self) -> PresenceTracker:
        return self._tracker
