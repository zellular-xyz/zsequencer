"""
This module defines the Flask blueprint for sequencer-related routes.
"""

from typing import Any

from flask import Blueprint, Response, request

from zsequencer.common import utils
from zsequencer.common.db import zdb
from zsequencer.common.errors import ErrorCodes
from zsequencer.common.response_utils import error_response, success_response
from zsequencer.config import zconfig

sequencer_blueprint = Blueprint("sequencer", __name__)


@sequencer_blueprint.route("/transactions", methods=["PUT"])
@utils.sequencer_only
def put_transactions() -> Response:
    """Endpoint to handle the PUT request for transactions."""
    if not request.is_json:
        return error_response(ErrorCodes.INVALID_REQUEST, "Request must be JSON.")

    req_data: dict[str, Any] = request.get_json(silent=True) or {}
    required_keys: list[str] = [
        "app_name",
        "txs",
        "node_id",
        "sig",
        "sequenced_index",
        "sequenced_hash",
        "sequenced_chaining_hash",
        "locked_index",
        "locked_hash",
        "locked_chaining_hash",
        "timestamp",
    ]
    error_message: str = utils.validate_request(req_data, required_keys)
    if error_message:
        return error_response(ErrorCodes.INVALID_REQUEST, error_message)

    concat_hash: str = "".join(tx["hash"] for tx in req_data["txs"])
    is_sig_verified: bool = utils.is_sig_verified(
        sig=req_data["sig"], node_id=req_data["node_id"], msg=concat_hash
    )
    if (
        not is_sig_verified
        or str(req_data["node_id"]) not in zconfig.NODES
        or req_data["app_name"] not in zconfig.APPS
    ):
        return error_response(ErrorCodes.PERMISSION_DENIED)

    data: dict[str, Any] = _put_transactions(req_data)
    return success_response(data=data)


def _put_transactions(req_data: dict[str, Any]) -> dict[str, Any]:
    """Process the transaction data."""
    # TODO: check if lock is required
    zdb.sequencer_init_txs(app_name=req_data["app_name"], txs=req_data["txs"])

    txs: dict[str, Any] = zdb.get_txs(
        app_name=req_data["app_name"],
        states={"sequenced", "locked", "finalized"},
        after=req_data["sequenced_index"],
    )

    last_finalized_tx: dict[str, Any] = zdb.get_last_tx(
        app_name=req_data["app_name"], state="finalized"
    )
    last_locked_tx: dict[str, Any] = zdb.get_last_tx(
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

    data: dict[str, Any] = {
        "txs": list(txs.values()),
        "finalized": {
            "index": last_finalized_tx.get("index", 0),
            "chaining_hash": last_finalized_tx.get("chaining_hash", ""),
            "hash": last_finalized_tx.get("hash", ""),
            "sig": last_finalized_tx.get("finalization_sig", ""),
        },
        "locked": {
            "index": last_locked_tx.get("index", 0),
            "chaining_hash": last_locked_tx.get("chaining_hash", ""),
            "hash": last_locked_tx.get("hash", ""),
            "sig": last_locked_tx.get("lock_sig", ""),
        },
    }

    return data
