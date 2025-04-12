"""This module defines the Flask blueprint for sequencer-related routes.
"""

from typing import Any

from flask import Blueprint, Response, request

from common import utils
from common.db import zdb
from common.errors import ErrorCodes
from common.response_utils import error_response, success_response
from config import zconfig

sequencer_blueprint = Blueprint("sequencer", __name__)


@sequencer_blueprint.route("/batches", methods=["PUT"])
@utils.sequencer_only
@utils.sequencer_simulation_malfunction
@utils.validate_version
@utils.validate_body_keys(
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
    ],
)
@utils.sequencer_only
def put_batches() -> Response:
    """Endpoint to handle the PUT request for batches."""
    req_data: dict[str, Any] = request.get_json(silent=True) or {}

    concat_hash: str = "".join(batch["hash"] for batch in req_data["batches"])
    is_eth_sig_verified: bool = utils.is_eth_sig_verified(
        signature=req_data["signature"],
        node_id=req_data["node_id"],
        message=concat_hash,
    )
    if (
        not is_eth_sig_verified
        or str(req_data["node_id"]) not in list(zconfig.NODES.keys())
        or req_data["app_name"] not in list(zconfig.APPS.keys())
    ):
        return error_response(ErrorCodes.PERMISSION_DENIED)

    data: dict[str, Any] = _put_batches(req_data)
    return success_response(data=data)


def _put_batches(req_data: dict[str, Any]) -> dict[str, Any]:
    """Process the batches data."""
    with zdb.sequencer_put_batches_lock:
        zdb.sequencer_init_batches(
            app_name=req_data["app_name"], initializing_batches=req_data["batches"],
        )

    batch_sequence = zdb.get_global_operational_batch_sequence(
        app_name=req_data["app_name"],
        after=req_data["sequenced_index"],
    )
    last_finalized_batch_record = zdb.get_last_operational_batch_record_or_empty(
        app_name=req_data["app_name"], state="finalized",
    )
    last_locked_batch_record = zdb.get_last_operational_batch_record_or_empty(
        app_name=req_data["app_name"], state="locked",
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
            "index", 0,
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
