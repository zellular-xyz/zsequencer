"""This module defines the Flask blueprint for sequencer-related routes."""

from typing import Any

from fastapi import APIRouter, Depends, Request, Response

from common import utils
from common.batch import get_batch_size_kb
from common.db import zdb
from common.errors import ErrorCodes, ErrorMessages
from common.response_utils import error_response, success_response
from config import zconfig
from sequencer.rate_limit import try_acquire_rate_limit_of_other_nodes

router = APIRouter()


@router.put(
    "/batches",
    dependencies=[
        Depends(utils.sequencer_only),
        Depends(utils.sequencer_simulation_malfunction),
        Depends(utils.validate_version),
        Depends(
            utils.validate_body_keys(
                required_keys=[
                    "app_name",
                    "batches",
                    "node_id",
                    "signature",
                    "sequenced_index",
                    "sequenced_hash",
                    "sequenced_chaining_hash",
                    "locked_index",
                    "locked_hash",
                    "locked_chaining_hash",
                    "timestamp",
                ]
            )
        ),
    ],
)
async def put_batches(request: Request) -> Response:
    if zdb.pause_node.is_set():
        return error_response(
            error_code=ErrorCodes.IS_PAUSED, error_message=ErrorMessages.IS_PAUSED
        )

    req_data = await request.json()
    initializing_batches = req_data["batches"]

    if not try_acquire_rate_limit_of_other_nodes(
        node_id=req_data["node_id"], batches=initializing_batches
    ):
        return error_response(
            error_code=ErrorCodes.BATCHES_LIMIT_EXCEEDED,
            error_message=ErrorMessages.BATCHES_LIMIT_EXCEEDED,
        )

    for batch in initializing_batches:
        if get_batch_size_kb(batch) > zconfig.MAX_BATCH_SIZE_KB:
            return error_response(
                error_code=ErrorCodes.BATCH_SIZE_EXCEEDED,
                error_message=ErrorMessages.BATCH_SIZE_EXCEEDED,
            )

    concat_hash = "".join(batch["hash"] for batch in req_data["batches"])
    is_eth_sig_verified = utils.is_eth_sig_verified(
        signature=req_data["signature"],
        node_id=req_data["node_id"],
        message=concat_hash,
    )

    if (
        not is_eth_sig_verified
        or str(req_data["node_id"]) not in list(zconfig.last_state.posting_nodes.keys())
        or req_data["app_name"] not in list(zconfig.APPS.keys())
    ):
        return error_response(ErrorCodes.PERMISSION_DENIED)

    data = _put_batches(req_data)
    return success_response(data=data)


def _put_batches(req_data: dict[str, Any]) -> dict[str, Any]:
    """Process the batches data."""
    with zdb.sequencer_put_batches_lock:
        zdb.sequencer_init_batches(
            app_name=req_data["app_name"],
            initializing_batches=req_data["batches"],
        )
    batch_sequence = zdb.get_global_operational_batch_sequence(
        app_name=req_data["app_name"],
        after=req_data["sequenced_index"],
    )
    last_finalized_batch_record = zdb.get_last_operational_batch_record_or_empty(
        app_name=req_data["app_name"],
        state="finalized",
    )
    last_finalized_index = last_finalized_batch_record.get("index", 0)
    last_locked_batch_record = zdb.get_last_operational_batch_record_or_empty(
        app_name=req_data["app_name"],
        state="locked",
    )
    if batch_sequence:
        if batch_sequence.get_last_or_empty()[
            "index"
        ] < last_finalized_batch_record.get("index", 0):
            last_finalized_batch_record = next(
                (
                    d
                    for d in batch_sequence.records(reverse=True)
                    if "finalization_signature" in d["batch"]
                ),
                {},
            )
        if batch_sequence.get_last_or_empty()["index"] < last_locked_batch_record.get(
            "index",
            0,
        ):
            last_locked_batch_record = next(
                (
                    d
                    for d in batch_sequence.records(reverse=True)
                    if "lock_signature" in d["batch"]
                ),
                {},
            )
    zdb.upsert_node_state(
        {
            "app_name": req_data["app_name"],
            "node_id": req_data["node_id"],
            "sequenced_index": req_data["sequenced_index"],
            "sequenced_hash": req_data["sequenced_hash"],
            "sequenced_chaining_hash": req_data["sequenced_chaining_hash"],
            "locked_index": req_data["locked_index"],
            "locked_hash": req_data["locked_hash"],
            "locked_chaining_hash": req_data["locked_chaining_hash"],
        },
    )

    # TODO: remove (create issue for testing)
    # if zconfig.NODE["id"] == "1":
    #     txs = {}
    last_finalized_batch = last_finalized_batch_record.get("batch", {})
    last_locked_batch = last_locked_batch_record.get("batch", {})
    return {
        "batches": batch_sequence.batches(),
        "last_finalized_index": last_finalized_index,
        "finalized": {
            "index": last_finalized_batch_record.get("index", 0),
            "chaining_hash": last_finalized_batch.get("chaining_hash", ""),
            "hash": last_finalized_batch.get("hash", ""),
            "signature": last_finalized_batch.get("finalization_signature", ""),
            "nonsigners": last_finalized_batch.get("finalized_nonsigners", []),
            "tag": last_finalized_batch.get("finalized_tag", 0),
        },
        "locked": {
            "index": last_locked_batch_record.get("index", 0),
            "chaining_hash": last_locked_batch.get("chaining_hash", ""),
            "hash": last_locked_batch.get("hash", ""),
            "signature": last_locked_batch.get("lock_signature", ""),
            "nonsigners": last_locked_batch.get("locked_nonsigners", []),
            "tag": last_locked_batch.get("locked_tag", 0),
        },
    }
