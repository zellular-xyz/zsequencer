from typing import TypedDict, cast

from common.state import State
from common.utils import get_utf8_size_kb


class Batch(TypedDict, total=False):
    body: str
    chaining_hash: str
    lock_signature: str
    locked_nonsigners: list[str]
    locked_tag: int
    finalization_signature: str
    finalized_nonsigners: list[str]
    finalized_tag: int


def get_batch_size_kb(batch: Batch) -> float:
    body = batch.get("body")
    if body is None:
        return 0.0
    return get_utf8_size_kb(body)


class BatchRecord(TypedDict, total=False):
    batch: Batch
    index: int
    state: State


class StatefulBatch(TypedDict, total=False):
    app_name: str
    node_id: str
    body: str
    chaining_hash: str
    lock_signature: str
    locked_nonsigners: list[str]
    locked_tag: int
    finalization_signature: str
    finalized_nonsigners: list[str]
    finalized_tag: int
    index: int
    state: State


def batch_record_to_stateful_batch(
    app_name: str, batch_record: BatchRecord
) -> StatefulBatch:
    return cast(
        "StatefulBatch",
        {
            key: batch_record.get(key)
            or batch_record.get("batch", {}).get(key)
            or {"app_name": app_name}.get(key)
            for key in StatefulBatch.__annotations__
        },
    )


def stateful_batch_to_batch_record(stateful_batch: StatefulBatch) -> BatchRecord:
    return cast(
        "BatchRecord",
        {
            "batch": {
                key: value
                for key, value in stateful_batch.items()
                if key in Batch.__annotations__
            },
            **{
                key: value
                for key, value in stateful_batch.items()
                if key in BatchRecord.__annotations__
            },
        },
    )
