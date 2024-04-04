import time
from typing import Any, Dict

from flask import Blueprint, Response, request

from config import zconfig
from shared_state import state

from ..common import utils
from ..common.db import zdb
from ..common.errors import ErrorCodes
from ..common.response_utils import error_response, success_response
from . import tasks

node_blueprint = Blueprint("node", __name__)


@node_blueprint.route("/dispute", methods=["POST"])
@utils.not_sequencer
def post_dispute() -> Response:
    if not request.is_json:
        return error_response(ErrorCodes.INVALID_REQUEST, "Request must be JSON.")

    req_data: Dict[str, Any] = request.get_json(silent=True) or {}
    required_keys: list[str] = ["sequencer_id", "txs", "timestamp"]
    error_message: str = utils.validate_request(req_data, required_keys)
    if error_message:
        return error_response(ErrorCodes.INVALID_REQUEST, error_message)

    if req_data["sequencer_id"] != zconfig.SEQUENCER["id"]:
        return error_response(ErrorCodes.INVALID_SEQUENCER)

    if state.get_missed_txs_number():
        timestamp: int = int(time.time())
        data: Dict[str, Any] = {
            "node_id": zconfig.NODE["id"],
            "old_sequencer_id": zconfig.SEQUENCER["id"],
            "new_sequencer_id": utils.get_next_sequencer_id(zconfig.SEQUENCER["id"]),
            "timestamp": timestamp,
            "sig": utils.sign(f'{zconfig.SEQUENCER["id"]}{timestamp}'),
        }
        return success_response(data=data)

    else:
        for tx in req_data["txs"]:
            tasks.init_tx(tx)

        return error_response(ErrorCodes.ISSUE_NOT_FOUND)


@node_blueprint.route("/state", methods=["GET"])
def get_state() -> Response:
    last_sequenced_tx: Dict[str, Any] = zdb.txs.get_last_tx_by_state("sequenced") or {}
    last_finalized_tx: Dict[str, Any] = zdb.txs.get_last_tx_by_state("finalized") or {}
    data: Dict[str, Any] = {
        "sequencer": zconfig.NODE["id"] == zconfig.SEQUENCER["id"],
        "sequencer_id": zconfig.SEQUENCER["id"],
        "node_id": zconfig.NODE["id"],
        "public_key": zconfig.NODE["public_key"],
        "address": zconfig.NODE["address"],
        "last_sequenced_index": last_sequenced_tx.get("index", 0),
        "last_sequenced_hash": last_sequenced_tx.get("hash", ""),
        "last_finalized_index": last_finalized_tx.get("index", 0),
        "last_finalized_hash": last_finalized_tx.get("hash", ""),
    }
    return success_response(data=data)


@node_blueprint.route("/finalized_transactions/last", methods=["GET"])
def get_last_finalized_tx() -> Response:
    last_finalized_tx: Dict[str, Any] = zdb.txs.get_last_tx_by_state("finalized") or {}
    return success_response(data=last_finalized_tx)


@node_blueprint.route("/distributed_keys", methods=["PUT"])
def put_distributed_keys() -> Response:
    if not request.is_json:
        return error_response(ErrorCodes.INVALID_REQUEST, "Request must be JSON.")

    req_data: Dict[str, Any] = request.get_json(silent=True) or {}
    if not req_data:
        return error_response(ErrorCodes.INVALID_REQUEST)

    if zdb.keys.get_public_shares():
        return error_response(ErrorCodes.PK_ALREADY_SET)

    zdb.keys.set_public_shares(req_data)
    return success_response(data={}, message="The distributed keys set successfully.")


@node_blueprint.route("/switch", methods=["POST"])
def post_switch_sequencer() -> Response:
    if not request.is_json:
        return error_response(ErrorCodes.INVALID_REQUEST, "Request must be JSON.")

    req_data: Dict[str, Any] = request.get_json(silent=True) or {}
    required_keys: list[str] = ["timestamp", "proofs"]
    error_message: str = utils.validate_request(req_data, required_keys)
    if error_message:
        return error_response(ErrorCodes.INVALID_REQUEST, error_message)

    if utils.is_switch_approved(req_data["proofs"]):
        tasks.switch_sequencer(req_data["proofs"], "RECEIVED")
        return success_response(data={}, message="The sequencer set successfully.")

    return error_response(ErrorCodes.SEQUENCER_CHANGE_NOT_APPROVED)


@node_blueprint.route("/transactions", methods=["GET"])
def get_transactions() -> Response:
    index: int = request.args.get("after", default=0, type=int)
    txs: Dict[str, Any] = zdb.txs.get_txs(after=index)
    return success_response(data=list(txs.values()))


@node_blueprint.route("/transaction", methods=["GET"])
def get_transaction() -> Response:
    search_term: str = request.args.get("search_term", default="", type=str)

    if not search_term:
        return error_response(ErrorCodes.INVALID_REQUEST)

    txs: Dict[str, Any] = zdb.txs.get_txs(search_term=search_term)
    if not txs:
        return error_response(ErrorCodes.NOT_FOUND)

    return success_response(data=list(txs.values())[0])
