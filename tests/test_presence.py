import time
import pytest
from unittest.mock import MagicMock
from aether.vision.presence import PresenceTracker
from aether.state import State, Event


def test_human_detected_emits_event():
    sm = MagicMock()
    sm.state = State.PRESENT
    tracker = PresenceTracker(absence_timeout_sec=10, state_machine=sm)
    tracker.update(human_detected=True, now=100.0)
    sm.handle_event.assert_not_called()


def test_absence_timeout_triggers_away():
    sm = MagicMock()
    sm.state = State.PRESENT
    tracker = PresenceTracker(absence_timeout_sec=10, state_machine=sm)
    tracker.update(human_detected=True, now=100.0)
    tracker.update(human_detected=False, now=105.0)
    sm.handle_event.assert_not_called()
    tracker.update(human_detected=False, now=111.0)
    sm.handle_event.assert_called_once_with(Event.HUMAN_ABSENT)


def test_human_returns_triggers_present():
    sm = MagicMock()
    sm.state = State.AWAY
    tracker = PresenceTracker(absence_timeout_sec=10, state_machine=sm)
    tracker._last_human_seen = 0.0
    tracker._absence_fired = True
    tracker.update(human_detected=True, now=200.0)
    sm.handle_event.assert_called_once_with(Event.HUMAN_DETECTED)


def test_brief_absence_does_not_trigger():
    sm = MagicMock()
    sm.state = State.PRESENT
    tracker = PresenceTracker(absence_timeout_sec=10, state_machine=sm)
    tracker.update(human_detected=True, now=100.0)
    tracker.update(human_detected=False, now=103.0)
    tracker.update(human_detected=True, now=106.0)
    sm.handle_event.assert_not_called()


def test_absence_only_fires_once():
    sm = MagicMock()
    sm.state = State.PRESENT
    tracker = PresenceTracker(absence_timeout_sec=10, state_machine=sm)
    tracker.update(human_detected=True, now=100.0)
    tracker.update(human_detected=False, now=111.0)
    tracker.update(human_detected=False, now=120.0)
    assert sm.handle_event.call_count == 1
