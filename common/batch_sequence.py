from __future__ import annotations
from typing import Any, Tuple
from collections.abc import Iterable, Mapping
from common.state import (
    OperationalState,
    OPERATIONAL_STATES,
    is_state_before_or_equal,
)
from common.batch import Batch, BatchRecord, get_batch_size_kb
from common.logger import zlogger
from common.extended_int import ExtendedInt


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
        self._size_kb = sum(get_batch_size_kb(batch) for batch in self._batches)

    @property
    def size_kb(self) -> float:
        return self._size_kb

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

    def records(self, reverse: bool = False) -> Iterable[BatchRecord]:
        for batch, index in zip(self.batches(reverse), self.indices(reverse)):
            yield BatchRecord(batch=batch, index=index, state=self._get_state(index))

    def indices(self, reverse: bool = False) -> Iterable[int]:
        index_range = range(
            self._index_offset,
            self.get_last_index_or_default(default=self.BEFORE_GLOBAL_INDEX_OFFSET) + 1,
        )
        if not reverse:
            return index_range
        else:
            return reversed(index_range)

    def batches(self, reverse: bool = False) -> Iterable[Batch]:
        return self._batches if not reverse else reversed(self._batches)

    def has_any(self, state: OperationalState = "sequenced") -> bool:
        return (
            self.get_last_index_or_default(
                state=state, default=self.BEFORE_GLOBAL_INDEX_OFFSET
            )
            != self.BEFORE_GLOBAL_INDEX_OFFSET
        )

    def get_first_index_or_default(
        self,
        state: OperationalState = "sequenced",
        *,
        default: int = BEFORE_GLOBAL_INDEX_OFFSET,
    ) -> int:
        return self._index_offset if self.has_any(state) else default

    def get_last_index_or_default(
        self,
        state: OperationalState = "sequenced",
        *,
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
        self._size_kb += get_batch_size_kb(batch)
        return self.get_last_index_or_default()

    def _includes_only_finalized_batches(self) -> bool:
        """
        Check if all batches in the sequence are in finalized state.
        Returns True if all batches are finalized, False otherwise.
        Empty sequence returns True as it has no non-finalized batches.
        """
        if not self._batches:
            return True

        last_finalized_index = self.get_last_index_or_default(
            state="finalized",
            default=self.BEFORE_GLOBAL_INDEX_OFFSET
        )
        last_index_of_sequence = self.get_last_index_or_default(default=self.BEFORE_GLOBAL_INDEX_OFFSET)

        return last_index_of_sequence <= last_finalized_index

    def extend(self, other: BatchSequence):
        if not other or len(other._batches) == 0:
            return

        if not self._includes_only_finalized_batches():
            raise ValueError("The sequence batches are not finalized yet!")

        if len(self) == 0:
            self._index_offset = other.index_offset
            self._batches = list(other.batches())
            self._each_state_last_index = dict(other._each_state_last_index)
            self._size_kb = other._size_kb
            return

        # Ensure the first batch of the new sequence aligns with the last batch of the current sequence
        expected_start_index = self.get_last_index_or_default() + 1
        if other.index_offset != expected_start_index:
            raise ValueError(
                f"Batch sequence must start at {expected_start_index}, but got {other.index_offset}."
            )

        for batch in other.batches():
            self.append(batch)

        for state, index in other._each_state_last_index.items():
            self.promote(index, state)

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

    def truncate_by_size(self, size_kb: float) -> BatchSequence:
        """
        Truncate the batch sequence up to a specified size in KB.

        Args:
            size_kb: Maximum size in KB for the truncated sequence
        """
        if size_kb <= 0 or not self:
            return self._create_empty()

        if size_kb >= self._size_kb:
            return self

        total_size = 0.0
        end_index = self.before_index_offset

        for record in self.records():
            batch_size = get_batch_size_kb(record["batch"])
            if total_size + batch_size > size_kb:
                break

            total_size += batch_size
            end_index = record["index"]

        return self.filter(end_inclusive=end_index) if end_index > self.before_index_offset else self._create_empty()

    def filter(
        self,
        target_state: OperationalState = "sequenced",
        *,
        exclude_state: OperationalState | None = None,
        start_exclusive: int | None = None,
        end_inclusive: int | None = None,
    ) -> BatchSequence:
        if exclude_state is not None and is_state_before_or_equal(
            exclude_state, target_state
        ):
            return self._create_empty()

        inf_supported_start_exclusive = ExtendedInt.from_optional_int(
            start_exclusive, none_as="-inf"
        )
        inf_supported_end_inclusive = ExtendedInt.from_optional_int(
            end_inclusive, none_as="inf"
        )

        if inf_supported_start_exclusive >= inf_supported_end_inclusive:
            return self._create_empty()

        target_state_last_index = ExtendedInt.from_optional_int(
            (
                None
                if target_state == "sequenced"
                else self.get_last_index_or_default(
                    target_state, default=self.BEFORE_GLOBAL_INDEX_OFFSET
                )
            ),
            none_as="inf",
        )
        if target_state_last_index == self.BEFORE_GLOBAL_INDEX_OFFSET:
            return self._create_empty()

        excluding_state_last_index = ExtendedInt.from_optional_int(
            (
                None
                if exclude_state is None
                else self.get_last_index_or_default(
                    exclude_state, default=self.BEFORE_GLOBAL_INDEX_OFFSET
                )
            ),
            none_as="-inf",
        )
        if excluding_state_last_index == self.BEFORE_GLOBAL_INDEX_OFFSET:
            excluding_state_last_index = ExtendedInt("-inf")

        final_start_inclusive = (
            max(
                inf_supported_start_exclusive,
                excluding_state_last_index,
                ExtendedInt(self.before_index_offset),
            )
            + 1
        )

        final_end_exclusive = (
            min(
                inf_supported_end_inclusive,
                target_state_last_index,
            )
            + 1
        )

        if final_start_inclusive >= final_end_exclusive:
            return self._create_empty()

        relative_final_start_inclusive = (
            final_start_inclusive - self._index_offset
        ).to_optional_int()
        relative_final_end_exclusive = (
            final_end_exclusive - self._index_offset
        ).to_optional_int()

        batches = self._batches[
            relative_final_start_inclusive:relative_final_end_exclusive
        ]
        first_index = self._index_offset + (
            0
            if relative_final_start_inclusive is None
            else relative_final_start_inclusive
        )
        last_index = first_index + len(batches) - 1

        return BatchSequence(
            index_offset=first_index,
            batches=batches,
            each_state_last_index={
                state: min(last_index, state_last_index)
                for state, state_last_index in self._each_state_last_index.items()
                if batches and state_last_index >= first_index
            },
        )

    def get_first_or_empty(self, state: OperationalState = "sequenced") -> BatchRecord:
        first_index = self.get_first_index_or_default(
            state, default=self.BEFORE_GLOBAL_INDEX_OFFSET
        )
        if first_index == self.BEFORE_GLOBAL_INDEX_OFFSET:
            return {}

        return BatchRecord(
            batch=self._get_batch_or_empty(first_index),
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
            batch=self._get_batch_or_empty(last_index),
            index=last_index,
            state=state,
        )

    def get_or_empty(self, index: int) -> BatchRecord:
        batch = self._get_batch_or_empty(index)

        if not batch:
            return {}

        return BatchRecord(
            batch=batch,
            index=index,
            state=self._get_state(index),
        )

    def _get_batch_or_empty(self, index: int) -> Batch:
        return self._get_batch_by_relative_index_or_empty(index - self._index_offset)

    def _get_state(self, index: int) -> OperationalState:
        if index < self.GLOBAL_INDEX_OFFSET:
            raise RuntimeError(f"The {index=} is invalid.")

        for state in reversed(OPERATIONAL_STATES):
            if index <= self.get_last_index_or_default(
                state, default=self.BEFORE_GLOBAL_INDEX_OFFSET
            ):
                return state

        raise RuntimeError(f"There is no batch with {index=}.")

    def _get_batch_by_relative_index_or_empty(self, relative_index: int) -> Batch:
        if relative_index < 0 or relative_index >= len(self._batches):
            return {}

        return self._batches[relative_index]

    def _create_empty(self) -> BatchSequence:
        return BatchSequence(index_offset=self._index_offset)
