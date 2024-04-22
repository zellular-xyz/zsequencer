from typing import Any, Dict

from flask import Blueprint, Response, request

from config import zconfig

from ..common import utils
from ..common.db import zdb
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
    if not is_verified or req_data["node_id"] not in zconfig.NODES:
        return error_response(ErrorCodes.PERMISSION_DENIED)

    with zdb._lock:
        if req_data["txs"]:
            zdb.sequencer_init_txs(req_data["txs"])

        zdb.upsert_node_state(
            req_data["node_id"],
            req_data["index"],
            req_data["chaining_hash"],
        )

        txs: Dict[str, Any] = zdb.get_txs(after=req_data["index"])
        sync_point: Dict[str, Any] = zdb.get_sync_point() or {}

    # TODO: remove (create issue for testing)
    # if zconfig.NODE["id"] == "1":
    #     txs = {}

    data: Dict[str, Any] = {
        "txs": list(txs.values()),
        "finalized": {
            "index": sync_point.get("index", 0),
            "chaining_hash": sync_point.get("chaining_hash", ""),
            "sig": sync_point.get("sig", ""),
        },
    }
    return success_response(data=data)
