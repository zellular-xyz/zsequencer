from __future__ import annotations
from typing import Any
from collections.abc import Iterable, Mapping, Iterator, Callable
import portion  # type: ignore[import-untyped]
from common.state import (
    OperationalState,
    next_state_or_none,
    OPERATIONAL_STATES,
    is_state_before_or_equal,
)
from common.batch import Batch, BatchRecord
from common.logger import zlogger


class BatchSequence:
    GLOBAL_INDEX_OFFSET = 1
    BEFORE_GLOBAL_INDEX_OFFSET = 0

    def __init__(
        self,
        index_offset: int | None = None,
        batches: Iterable[Batch] | None = None,
        each_state_last_index: Mapping[OperationalState, int] | None = None,
    ) -> None:
        index_offset = (
            index_offset if index_offset is not None else self.GLOBAL_INDEX_OFFSET
        )
        batches = batches or []
        each_state_last_index = each_state_last_index or {}

        if "sequenced" in each_state_last_index.keys():
            raise ValueError(
                "All the batches are considered sequenced, so there is no need to "
                "store the last index for the sequenced batches."
            )

        self._index_offset = index_offset
        self._batches = list(batches)
        self._each_state_last_index = dict(each_state_last_index)

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> BatchSequence:
        return BatchSequence(
            index_offset=mapping["index_offset"],
            batches=mapping["batches"],
            each_state_last_index=mapping["each_state_last_index"],
        )

    @property
    def index_offset(self) -> int:
        return self._index_offset

    @property
    def before_index_offset(self) -> int:
        return self._index_offset - 1

    def __bool__(self) -> bool:
        return bool(self._batches)

    def __len__(self) -> int:
        return len(self._batches)

    def __add__(self, other: Iterable[Batch]) -> BatchSequence:
        return BatchSequence(
            index_offset=self._index_offset,
            batches=self._batches + list(other),
            each_state_last_index=self._each_state_last_index,
        )

    def records(self) -> Iterator[BatchRecord]:
        index_calculator = self._generate_relative_index_to_index_calculator()
        for relative_index, batch in enumerate(self._batches):
            index = index_calculator(relative_index)
            yield BatchRecord(batch=batch, index=index, state=self.get_state(index))

    def indices(self) -> Iterable[int]:
        return portion.iterate(self.generate_index_interval(), step=1)

    def batches(self) -> Iterable[Batch]:
        return self._batches

    def has_any(self, state: OperationalState = "sequenced") -> bool:
        return (
            self.get_last_index_or_default(
                state=state, default=self.BEFORE_GLOBAL_INDEX_OFFSET
            )
            != self.BEFORE_GLOBAL_INDEX_OFFSET
        )

    def generate_index_interval(
        self,
        state: OperationalState = "sequenced",
        exclude_next_states: bool = False,
    ) -> portion.Interval:
        result = portion.closed(
            self.get_first_index_or_default(state=state, default=self.index_offset),
            self.get_last_index_or_default(
                state=state, default=self.before_index_offset
            ),
        )

        if (
            state is not None
            and exclude_next_states
            and (next_state := next_state_or_none(state))
        ):
            result -= self.generate_index_interval(
                next_state, exclude_next_states=False
            )

        return result

    def get_first_index_or_default(
        self,
        state: OperationalState = "sequenced",
        default: int = BEFORE_GLOBAL_INDEX_OFFSET,
    ) -> int:
        if not self.has_any(state):
            return default
        return self._index_offset

    def get_last_index_or_default(
        self,
        state: OperationalState = "sequenced",
        default: int = BEFORE_GLOBAL_INDEX_OFFSET,
    ) -> int:
        if state == "sequenced":
            if not self._batches:
                return default
            else:
                return self._index_offset + len(self._batches) - 1
        else:
            return self._each_state_last_index.get(state, default)

    def append(self, batch: Batch) -> int:
        self._batches.append(batch)
        return self.get_last_index_or_default()

    def promote(self, last_index: int, target_state: OperationalState) -> None:
        feasible_last_index = min(
            last_index,
            self.get_last_index_or_default(default=self.BEFORE_GLOBAL_INDEX_OFFSET),
        )

        if feasible_last_index != last_index:
            zlogger.warning(
                f"The promoting {last_index=} was changed to {feasible_last_index=} "
                "due to the sequence's maximum available index."
            )

        if feasible_last_index <= self.BEFORE_GLOBAL_INDEX_OFFSET:
            return

        for current_state in OPERATIONAL_STATES:
            if current_state == "sequenced":
                continue

            if is_state_before_or_equal(current_state, target_state):
                self._each_state_last_index[current_state] = max(
                    self._each_state_last_index.get(current_state, feasible_last_index),
                    feasible_last_index,
                )

    def to_mapping(self) -> Mapping[str, Any]:
        return {
            "index_offset": self._index_offset,
            "batches": self._batches,
            "each_state_last_index": {
                state: last_index
                for state, last_index in self._each_state_last_index.items()
            },
        }

    def slice(self, index_interval: portion.Interval) -> BatchSequence:
        if index_interval.empty:
            return BatchSequence(index_offset=self._index_offset)

        relative_index_calculator = self._generate_index_to_relative_index_calculator()
        relative_index_interval = index_interval.apply(
            lambda x: x.replace(
                lower=(
                    x.lower
                    if x.lower == -portion.inf
                    else relative_index_calculator(x.lower)
                ),
                upper=(
                    x.upper
                    if x.upper == portion.inf
                    else relative_index_calculator(x.upper)
                ),
            )
        )

        feasible_relative_index_interval = relative_index_interval & portion.closed(
            0, portion.inf
        )

        if not feasible_relative_index_interval.atomic:
            raise ValueError(
                f"The {feasible_relative_index_interval=} from "
                f"{relative_index_interval=} and {index_interval=} is not atomic."
            )

        closed_lower_relative_index = None
        if not feasible_relative_index_interval.contains(0):
            if relative_index_interval.left == portion.CLOSED:
                closed_lower_relative_index = feasible_relative_index_interval.lower
            else:
                closed_lower_relative_index = feasible_relative_index_interval.lower + 1

        open_upper_relative_index = None
        if feasible_relative_index_interval.upper != portion.inf:
            if feasible_relative_index_interval.right == portion.CLOSED:
                open_upper_relative_index = feasible_relative_index_interval.upper + 1
            else:
                open_upper_relative_index = feasible_relative_index_interval.upper

        batches = self._batches[closed_lower_relative_index:open_upper_relative_index]
        first_index = self._index_offset + (
            closed_lower_relative_index
            if closed_lower_relative_index is not None and batches
            else 0
        )
        last_index = first_index + len(batches) - 1

        return BatchSequence(
            index_offset=first_index,
            batches=batches,
            each_state_last_index=(
                {
                    state: min(last_index, state_last_index)
                    for state, state_last_index in self._each_state_last_index.items()
                }
                if batches
                else None
            ),
        )

    def get_first_or_empty(self, state: OperationalState = "sequenced") -> BatchRecord:
        first_index = self.get_first_index_or_default(
            state, default=self.BEFORE_GLOBAL_INDEX_OFFSET
        )
        if first_index == self.BEFORE_GLOBAL_INDEX_OFFSET:
            return {}

        return BatchRecord(
            batch=self.get_batch_or_empty(first_index),
            index=first_index,
            state=state,
        )

    def get_last_or_empty(self, state: OperationalState = "sequenced") -> BatchRecord:
        last_index = self.get_last_index_or_default(
            state, default=self.BEFORE_GLOBAL_INDEX_OFFSET
        )
        if last_index == self.BEFORE_GLOBAL_INDEX_OFFSET:
            return {}

        return BatchRecord(
            batch=self.get_batch_or_empty(last_index),
            index=last_index,
            state=state,
        )

    def get_or_empty(self, index: int) -> BatchRecord:
        batch = self.get_batch_or_empty(index)

        if not batch:
            return {}

        return BatchRecord(
            batch=batch,
            index=index,
            state=self.get_state(index),
        )

    def get_batch_or_empty(self, index: int) -> Batch:
        batch = self._get_batch_by_relative_index_or_empty(
            self._index_to_relative_index(index)
        )
        if not batch:
            return {}
        return batch

    def get_state(self, index: int) -> OperationalState:
        state = self.get_state_or_none(index)

        if state is None:
            raise RuntimeError(f"There is no batch with {index=}.")

        return state

    def get_state_or_none(self, index: int) -> OperationalState | None:
        if index < self.GLOBAL_INDEX_OFFSET:
            return None

        for state in reversed(OPERATIONAL_STATES):
            if index <= self.get_last_index_or_default(
                state, default=self.BEFORE_GLOBAL_INDEX_OFFSET
            ):
                return state

        return None

    def _get_batch_by_relative_index_or_empty(self, relative_index: int) -> Batch:
        if relative_index < 0 or relative_index >= len(self._batches):
            return {}

        return self._batches[relative_index]

    def _generate_index_to_relative_index_calculator(self) -> Callable[[int], int]:
        index_offset = self._index_offset
        return lambda index: index - index_offset

    def _generate_relative_index_to_index_calculator(self) -> Callable[[int], int]:
        index_offset = self._index_offset
        return lambda relative_index: relative_index + index_offset

    def _index_to_relative_index(self, index: int) -> int:
        return index - self._index_offset
