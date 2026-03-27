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
