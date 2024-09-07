"""
This module defines the Flask blueprint for sequencer-related routes.
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
@utils.validate_request
@utils.sequencer_only
def put_batches() -> Response:
    """Endpoint to handle the PUT request for batches."""
    req_data: dict[str, Any] = request.get_json(silent=True) or {}

    required_keys: list[str] = [
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
    error_message: str = utils.validate_keys(req_data, required_keys)
    if error_message:
        return error_response(ErrorCodes.INVALID_REQUEST, error_message)

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
    with zdb.lock:
        zdb.sequencer_init_batches(app_name=req_data["app_name"], batches_data=req_data["batches"])

    batches: dict[str, Any] = zdb.get_batches(
        app_name=req_data["app_name"],
        states={"sequenced", "locked", "finalized"},
        after=req_data["sequenced_index"],
    )
    last_finalized_batch: dict[str, Any] = zdb.get_last_batch(
        app_name=req_data["app_name"], state="finalized"
    )
    last_locked_batch: dict[str, Any] = zdb.get_last_batch(
        app_name=req_data["app_name"], state="locked"
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

    return {
        "batches": sorted(batches.values(), key=lambda x: x['index']),
        "finalized": {
            "index": last_finalized_batch.get("index", 0),
            "chaining_hash": last_finalized_batch.get("chaining_hash", ""),
            "hash": last_finalized_batch.get("hash", ""),
            "signature": last_finalized_batch.get("finalization_signature", ""),
            "nonsigners": last_finalized_batch.get("nonsigners", []),
        },
        "locked": {
            "index": last_locked_batch.get("index", 0),
            "chaining_hash": last_locked_batch.get("chaining_hash", ""),
            "hash": last_locked_batch.get("hash", ""),
            "signature": last_locked_batch.get("lock_signature", ""),
            "nonsigners": last_locked_batch.get("nonsigners", []),
        },
    }
