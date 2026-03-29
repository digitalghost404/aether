import pytest
from aether.state import State, Event, StateMachine, InvalidTransition


def test_initial_state_is_present():
    sm = StateMachine()
    assert sm.state == State.PRESENT


def test_present_to_away():
    transitions = []
    sm = StateMachine(on_transition=lambda t: transitions.append(t))
    sm.handle_event(Event.HUMAN_ABSENT)
    assert sm.state == State.AWAY
    assert len(transitions) == 1
    assert transitions[0].from_state == State.PRESENT
    assert transitions[0].to_state == State.AWAY


def test_away_to_present():
    sm = StateMachine()
    sm.handle_event(Event.HUMAN_ABSENT)
    assert sm.state == State.AWAY

    transitions = []
    sm = StateMachine(on_transition=lambda t: transitions.append(t))
    sm.handle_event(Event.HUMAN_ABSENT)
    sm.handle_event(Event.HUMAN_DETECTED)
    assert sm.state == State.PRESENT
    assert len(transitions) == 2


def test_duplicate_present_ignored():
    transitions = []
    sm = StateMachine(on_transition=lambda t: transitions.append(t))
    sm.handle_event(Event.HUMAN_DETECTED)
    assert sm.state == State.PRESENT
    assert len(transitions) == 0


def test_duplicate_away_ignored():
    transitions = []
    sm = StateMachine(on_transition=lambda t: transitions.append(t))
    sm.handle_event(Event.HUMAN_ABSENT)
    sm.handle_event(Event.HUMAN_ABSENT)
    assert sm.state == State.AWAY
    assert len(transitions) == 1


def test_transition_has_reason():
    transitions = []
    sm = StateMachine(on_transition=lambda t: transitions.append(t))
    sm.handle_event(Event.HUMAN_ABSENT)
    assert transitions[0].reason == "human_absent"


def test_present_to_focus():
    transitions = []
    sm = StateMachine(on_transition=lambda t: transitions.append(t))
    sm.handle_event(Event.FOCUS_START)
    assert sm.state == State.FOCUS
    assert len(transitions) == 1
    assert transitions[0].from_state == State.PRESENT
    assert transitions[0].to_state == State.FOCUS


def test_focus_to_present():
    sm = StateMachine()
    sm.handle_event(Event.FOCUS_START)
    sm.handle_event(Event.FOCUS_STOP)
    assert sm.state == State.PRESENT


def test_present_to_party():
    sm = StateMachine()
    sm.handle_event(Event.PARTY_START)
    assert sm.state == State.PARTY


def test_party_to_present():
    sm = StateMachine()
    sm.handle_event(Event.PARTY_START)
    sm.handle_event(Event.PARTY_STOP)
    assert sm.state == State.PRESENT


def test_present_to_sleep():
    sm = StateMachine()
    sm.handle_event(Event.SLEEP_START)
    assert sm.state == State.SLEEP


def test_sleep_cancel_to_present():
    sm = StateMachine()
    sm.handle_event(Event.SLEEP_START)
    sm.handle_event(Event.SLEEP_CANCEL)
    assert sm.state == State.PRESENT


def test_sleep_complete_to_away():
    sm = StateMachine()
    sm.handle_event(Event.SLEEP_START)
    sm.handle_event(Event.SLEEP_COMPLETE)
    assert sm.state == State.AWAY


def test_away_cannot_enter_focus():
    sm = StateMachine()
    sm.handle_event(Event.HUMAN_ABSENT)
    assert sm.state == State.AWAY
    result = sm.handle_event(Event.FOCUS_START)
    assert result is None
    assert sm.state == State.AWAY


def test_away_cannot_enter_party():
    sm = StateMachine()
    sm.handle_event(Event.HUMAN_ABSENT)
    result = sm.handle_event(Event.PARTY_START)
    assert result is None
    assert sm.state == State.AWAY


def test_away_cannot_enter_sleep():
    sm = StateMachine()
    sm.handle_event(Event.HUMAN_ABSENT)
    result = sm.handle_event(Event.SLEEP_START)
    assert result is None
    assert sm.state == State.AWAY


def test_focus_cannot_enter_party():
    sm = StateMachine()
    sm.handle_event(Event.FOCUS_START)
    result = sm.handle_event(Event.PARTY_START)
    assert result is None
    assert sm.state == State.FOCUS


def test_focus_ignores_human_absent():
    sm = StateMachine()
    sm.handle_event(Event.FOCUS_START)
    result = sm.handle_event(Event.HUMAN_ABSENT)
    assert result is None
    assert sm.state == State.FOCUS


def test_party_ignores_human_absent():
    sm = StateMachine()
    sm.handle_event(Event.PARTY_START)
    result = sm.handle_event(Event.HUMAN_ABSENT)
    assert result is None
    assert sm.state == State.PARTY
