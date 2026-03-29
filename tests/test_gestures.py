import time
import pytest
from aether.vision.gestures import GestureClassifier, Gesture
from aether.config import GestureConfig


def make_classifier(consecutive=2, fist_frames=4, cooldown=1):
    cfg = GestureConfig(
        consecutive_frames=consecutive,
        fist_hold_frames=fist_frames,
        cooldown_sec=cooldown,
        feedback_flash=False,
    )
    return GestureClassifier(cfg)


def _thumbs_up_landmarks():
    landmarks = [(0.5, 0.5)] * 21
    landmarks[4] = (0.5, 0.3)
    landmarks[2] = (0.5, 0.5)
    landmarks[8] = (0.4, 0.7)
    landmarks[6] = (0.4, 0.5)
    landmarks[12] = (0.45, 0.7)
    landmarks[10] = (0.45, 0.5)
    landmarks[16] = (0.5, 0.7)
    landmarks[14] = (0.5, 0.5)
    landmarks[20] = (0.55, 0.7)
    landmarks[18] = (0.55, 0.5)
    return landmarks


def _thumbs_down_landmarks():
    landmarks = list(_thumbs_up_landmarks())
    landmarks[4] = (0.5, 0.7)
    landmarks[2] = (0.5, 0.5)
    return landmarks


def _fist_landmarks():
    landmarks = [(0.5, 0.5)] * 21
    for tip, pip in [(4, 2), (8, 6), (12, 10), (16, 14), (20, 18)]:
        landmarks[tip] = (0.5, 0.7)
        landmarks[pip] = (0.5, 0.5)
    return landmarks


def _open_hand_landmarks():
    landmarks = [(0.5, 0.5)] * 21
    for tip, pip in [(4, 2), (8, 6), (12, 10), (16, 14), (20, 18)]:
        landmarks[tip] = (0.5, 0.3)
        landmarks[pip] = (0.5, 0.5)
    return landmarks


def test_classify_thumbs_up():
    gc = make_classifier()
    result = gc._classify_landmarks(_thumbs_up_landmarks())
    assert result == Gesture.THUMBS_UP


def test_classify_thumbs_down():
    gc = make_classifier()
    result = gc._classify_landmarks(_thumbs_down_landmarks())
    assert result == Gesture.THUMBS_DOWN


def test_classify_fist():
    gc = make_classifier()
    result = gc._classify_landmarks(_fist_landmarks())
    assert result == Gesture.FIST


def test_classify_open_hand_is_none():
    gc = make_classifier()
    result = gc._classify_landmarks(_open_hand_landmarks())
    assert result is None


def test_debounce_requires_consecutive_frames():
    gc = make_classifier(consecutive=3)
    assert gc.update(_thumbs_up_landmarks()) is None
    assert gc.update(_thumbs_up_landmarks()) is None
    assert gc.update(_thumbs_up_landmarks()) == Gesture.THUMBS_UP


def test_cooldown_prevents_repeated_fire():
    gc = make_classifier(consecutive=1, cooldown=10)
    assert gc.update(_thumbs_up_landmarks()) == Gesture.THUMBS_UP
    assert gc.update(_thumbs_up_landmarks()) is None


def test_fist_hold_requires_more_frames():
    gc = make_classifier(consecutive=2, fist_frames=4)
    assert gc.update(_fist_landmarks()) is None
    assert gc.update(_fist_landmarks()) is None
    assert gc.update(_fist_landmarks()) is None
    assert gc.update(_fist_landmarks()) == Gesture.FIST


def test_interrupted_gesture_resets():
    gc = make_classifier(consecutive=3)
    gc.update(_thumbs_up_landmarks())
    gc.update(_thumbs_up_landmarks())
    gc.update(_open_hand_landmarks())
    gc.update(_thumbs_up_landmarks())
    assert gc.update(_thumbs_up_landmarks()) is None
    assert gc.update(_thumbs_up_landmarks()) == Gesture.THUMBS_UP
