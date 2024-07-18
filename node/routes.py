"""This module defines the Flask blueprint for node-related routes."""

import time
from typing import Any

from flask import Blueprint, Response, request

from zsequencer.common import utils
from zsequencer.common.db import zdb
from zsequencer.common.errors import ErrorCodes
from zsequencer.common.response_utils import error_response, success_response
from zsequencer.config import zconfig

from . import tasks

node_blueprint = Blueprint("node", __name__)


# TODO: should remove
@node_blueprint.route("/db", methods=["GET"])
def get_db() -> dict[str, Any]:
    """Get the state of the in-memory database."""
    apps_data: dict[str, Any] = {}

    for app_name in zconfig.APPS:
        sequenced_num: int = zdb.get_last_tx(app_name, "sequenced").get("index", 0)
        locked_num: int = zdb.get_last_tx(app_name, "locked").get("index", 0)
        finalized_num: int = zdb.get_last_tx(app_name, "finalized").get("index", 0)
        all_num: int = len(zdb.apps[app_name]["transactions"])
        apps_data[app_name] = {
            "transactions_state": {
                "sequenced": sequenced_num,
                "locked": locked_num,
                "finalized": finalized_num,
                "all": all_num,
            }
            # "nodes_state": zdb.apps[app_name]["nodes_state"],
            # "transactions": sorted(
            #     list(zdb.apps[app_name]["transactions"].values()),
            #     key=lambda m: m["index"],
            # ),
        }

    return apps_data


@node_blueprint.route("/transactions", methods=["PUT"])
@utils.not_sequencer
def put_transactions() -> Response:
    """Put new transactions into the database."""
    req_data: dict[str, Any] = request.get_json(silent=True) or {}
    required_keys: list[str] = ["app_name", "transactions", "timestamp"]
    error_message: str = utils.validate_request(req_data, required_keys)
    if error_message:
        return error_response(ErrorCodes.INVALID_REQUEST, error_message)

    # TODO: check the sender authorization
    zdb.init_txs(req_data["app_name"], req_data["transactions"])
    return success_response(data={}, message="The transactions received successfully.")


@node_blueprint.route("/dispute", methods=["POST"])
@utils.not_sequencer
def post_dispute() -> Response:
    """Handle a dispute by initializing transactions if required."""
    if not request.is_json:
        return error_response(ErrorCodes.INVALID_REQUEST, "Request must be JSON.")

    req_data: dict[str, Any] = request.get_json(silent=True) or {}
    required_keys: list[str] = ["sequencer_id", "app_name", "txs", "timestamp"]
    error_message: str = utils.validate_request(req_data, required_keys)
    if error_message:
        return error_response(ErrorCodes.INVALID_REQUEST, error_message)

    if req_data["sequencer_id"] != zconfig.SEQUENCER["id"]:
        return error_response(ErrorCodes.INVALID_SEQUENCER)

    if zdb.has_missed_txs():
        timestamp: int = int(time.time())
        data: dict[str, Any] = {
            "node_id": zconfig.NODE["id"],
            "old_sequencer_id": zconfig.SEQUENCER["id"],
            "new_sequencer_id": utils.get_next_sequencer_id(zconfig.SEQUENCER["id"]),
            "timestamp": timestamp,
            "sig": utils.sign(f'{zconfig.SEQUENCER["id"]}{timestamp}'),
        }
        return success_response(data=data)

    zdb.init_txs(req_data["app_name"], req_data["txs"])
    return error_response(ErrorCodes.ISSUE_NOT_FOUND)


@node_blueprint.route("/state", methods=["GET"])
def get_state() -> Response:
    """Get the state of the node and its apps."""
    data: dict[str, Any] = {
        "sequencer": zconfig.NODE["id"] == zconfig.SEQUENCER["id"],
        "sequencer_id": zconfig.SEQUENCER["id"],
        "node_id": zconfig.NODE["id"],
        "public_key": str(zconfig.NODE["public_key"]),
        "address": zconfig.NODE["address"],
        "apps": {},
    }

    for app_name in zconfig.APPS:
        last_sequenced_tx = zdb.get_last_tx(app_name, "sequenced")
        last_locked_tx = zdb.get_last_tx(app_name, "locked")
        last_finalized_tx = zdb.get_last_tx(app_name, "finalized")

        data[app_name] = {
            "last_sequenced_index": last_sequenced_tx.get("index", 0),
            "last_sequenced_hash": last_sequenced_tx.get("hash", ""),
            "last_locked_index": last_locked_tx.get("index", 0),
            "last_locked_hash": last_locked_tx.get("hash", ""),
            "last_finalized_index": last_finalized_tx.get("index", 0),
            "last_finalized_hash": last_finalized_tx.get("hash", ""),
        }
    return success_response(data=data)


@node_blueprint.route("/<string:app_name>/transactions/finalized/last", methods=["GET"])
def get_last_finalized_tx(app_name: str) -> Response:
    """Get the last finalized transaction for a given app."""
    if not app_name:
        return error_response(ErrorCodes.INVALID_REQUEST, "app_name is required")

    last_finalized_tx: dict[str, Any] = zdb.get_last_tx(app_name, "finalized")
    return success_response(data=last_finalized_tx)


@node_blueprint.route("/distributed_keys", methods=["PUT"])
def put_distributed_keys() -> Response:
    """Put distributed keys into the database."""
    if not request.is_json:
        return error_response(ErrorCodes.INVALID_REQUEST, "Request must be JSON.")

    req_data: dict[str, Any] = request.get_json(silent=True) or {}
    if not req_data:
        return error_response(ErrorCodes.INVALID_REQUEST)

    if zdb.get_public_shares():
        return error_response(ErrorCodes.PK_ALREADY_SET)

    zdb.set_public_shares(req_data)
    return success_response(data={}, message="The distributed keys set successfully.")


@node_blueprint.route("/switch", methods=["POST"])
def post_switch_sequencer() -> Response:
    """Switch the sequencer based on the provided proofs."""
    if not request.is_json:
        return error_response(ErrorCodes.INVALID_REQUEST, "Request must be JSON.")

    req_data: dict[str, Any] = request.get_json(silent=True) or {}
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
    """Get transactions for a given app and states."""
    required_keys: list[str] = ["app_name", "states"]
    error_message: str = utils.validate_request(request.args, required_keys)
    if error_message:
        return error_response(ErrorCodes.INVALID_REQUEST, error_message)

    app_name: str = request.args["app_name"]
    after: int | None = request.args.get("after", default=None, type=int)
    states: set[str] = set(request.args.getlist("states", type=str))

    txs: dict[str, Any] = zdb.get_txs(app_name, states, after)
    return success_response(data=list(txs.values()))


@node_blueprint.route("/transaction", methods=["GET"])
def get_transaction() -> Response:
    """Get a specific transaction by its hash."""
    required_keys: list[str] = ["app_name", "hash"]
    error_message: str = utils.validate_request(request.args, required_keys)
    if error_message:
        return error_response(ErrorCodes.INVALID_REQUEST, error_message)

    app_name: str = request.args["app_name"]
    tx_hash: str = request.args["hash"]
    tx: dict[str, Any] = zdb.get_tx(app_name=app_name, tx_hash=tx_hash)
    if not tx:
        return error_response(ErrorCodes.NOT_FOUND)

    return success_response(data=tx)
