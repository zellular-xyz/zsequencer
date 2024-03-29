from typing import Any, Dict

from flask import Blueprint, Response, request

import config

from ..common import db, utils
from ..common.errors import ErrorCodes
from ..common.response_utils import error_response, success_response

sequencer_blueprint = Blueprint("sequencer", __name__)


@sequencer_blueprint.route("/transactions", methods=["PUT"])
@utils.sequencer_only
def put_transactions() -> Response:
    if not request.is_json:
        return error_response(ErrorCodes.INVALID_REQUEST, "Request must be JSON.")

    req_data: Dict[str, Any] = request.get_json(silent=True) or {}
    required_keys: list[str] = ["node_id", "index", "chaining_hash", "sig", "txs"]

    error_message: str = utils.validate_request(req_data, required_keys)
    if error_message:
        return error_response(ErrorCodes.INVALID_REQUEST, error_message)

    concat_hash: str = "".join(tx["hash"] for tx in req_data["txs"])
    is_verified: bool = utils.is_sig_verified(
        req_data["sig"], req_data["node_id"], concat_hash
    )
    if not is_verified or req_data["node_id"] not in config.NODES:
        return error_response(ErrorCodes.PERMISSION_DENIED)

    with db.insertion_lock:
        db.insert_txs(req_data["txs"])
        db.upsert_node_state(
            req_data["node_id"],
            req_data["index"],
            req_data["chaining_hash"],
        )

        txs: list[Dict[str, Any]] = db.get_txs(req_data["index"])
        sync_point: Dict[str, Any] = db.get_sync_point() or {}

    # TODO: remove (create issue for testing)
    if config.NODE["id"] == "1":
        txs = []

    data: Dict[str, Any] = {
        "txs": txs,
        "finalized": {
            "index": sync_point.get("index", 0),
            "chaining_hash": sync_point.get("chaining_hash", ""),
            "sig": sync_point.get("sig", ""),
        },
    }
    return success_response(data=data)
