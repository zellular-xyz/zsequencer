from __future__ import annotations
from typing import Literal, cast
from collections.abc import Sequence


# TODO: Replace with an enum when web schemas are supported.
OperationalState = Literal["sequenced", "locked", "finalized"]
State = Literal["initialized"] | OperationalState
OPERATIONAL_STATES: Sequence[OperationalState] = ("sequenced", "locked", "finalized")
STATES: Sequence[State] = ("initialized", *OPERATIONAL_STATES)


def is_state_before_or_equal(first: State, other: State) -> bool:
    return STATES.index(first) <= STATES.index(other)


def next_state_or_none(state: State) -> OperationalState | None:
    state_index = STATES.index(state)
    return (
        None
        if state_index + 1 >= len(STATES)
        else cast(OperationalState, STATES[state_index])
    )
