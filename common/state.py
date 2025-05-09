from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

InitializedState = Literal["initialized"]
SequencedState = Literal["sequenced"]
LockedState = Literal["locked"]
FinalizedState = Literal["finalized"]

# TODO: Replace with an enum when web schemas are supported.
OperationalState = SequencedState | LockedState | FinalizedState
State = InitializedState | OperationalState

OPERATIONAL_STATES: Sequence[OperationalState] = ("sequenced", "locked", "finalized")
STATES: Sequence[State] = ("initialized", *OPERATIONAL_STATES)


def is_state_before_or_equal(base_state: State, comparison_state: State) -> bool:
    return STATES.index(base_state) <= STATES.index(comparison_state)
