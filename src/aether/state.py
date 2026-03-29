from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Callable


class State(Enum):
    PRESENT = "present"
    AWAY = "away"
    FOCUS = "focus"
    PARTY = "party"
    SLEEP = "sleep"


class Event(Enum):
    HUMAN_DETECTED = "human_detected"
    HUMAN_ABSENT = "human_absent"
    FOCUS_START = "focus_start"
    FOCUS_STOP = "focus_stop"
    PARTY_START = "party_start"
    PARTY_STOP = "party_stop"
    SLEEP_START = "sleep_start"
    SLEEP_CANCEL = "sleep_cancel"
    SLEEP_COMPLETE = "sleep_complete"


@dataclass(frozen=True)
class Transition:
    from_state: State
    to_state: State
    reason: str
    timestamp: datetime


TRANSITION_TABLE: dict[tuple[State, Event], State] = {
    # Phase 1
    (State.PRESENT, Event.HUMAN_ABSENT): State.AWAY,
    (State.AWAY, Event.HUMAN_DETECTED): State.PRESENT,
    # Phase 2 — FOCUS
    (State.PRESENT, Event.FOCUS_START): State.FOCUS,
    (State.FOCUS, Event.FOCUS_STOP): State.PRESENT,
    # Phase 2 — PARTY
    (State.PRESENT, Event.PARTY_START): State.PARTY,
    (State.PARTY, Event.PARTY_STOP): State.PRESENT,
    # Phase 2 — SLEEP
    (State.PRESENT, Event.SLEEP_START): State.SLEEP,
    (State.SLEEP, Event.SLEEP_CANCEL): State.PRESENT,
    (State.SLEEP, Event.SLEEP_COMPLETE): State.AWAY,
}


class InvalidTransition(Exception):
    pass


class StateMachine:
    def __init__(self, on_transition: Callable[[Transition], None] | None = None):
        self.state = State.PRESENT
        self._on_transition = on_transition

    def handle_event(self, event: Event) -> Transition | None:
        key = (self.state, event)
        new_state = TRANSITION_TABLE.get(key)

        if new_state is None:
            return None

        transition = Transition(
            from_state=self.state,
            to_state=new_state,
            reason=event.value,
            timestamp=datetime.now(timezone.utc),
        )
        self.state = new_state

        if self._on_transition:
            self._on_transition(transition)

        return transition
