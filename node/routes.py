"""This module defines the Flask blueprint for node-related routes."""

import time
from typing import Any

from flask import Blueprint, Response, request

from common import utils
from common.db import zdb
from common.errors import ErrorCodes
from common.logger import zlogger
from common.response_utils import error_response, success_response
from common.batch import batch_record_to_stateful_batch
from config import zconfig
from . import tasks

node_blueprint = Blueprint("node", __name__)


@node_blueprint.route("/batches", methods=["PUT"])
@utils.validate_request
@utils.not_sequencer
def put_bulk_batches() -> Response:
    """Put a new batch into the database."""
    valid_apps = set(zconfig.APPS)
    batches_mapping = request.get_json()

    for app_name, batches in batches_mapping.items():
        if app_name not in valid_apps:
            zlogger.warning(f"{app_name} is not a valid app.")
            continue

        zlogger.info(f"The batches are going to be initialized. app: {app_name}, number of batches: {len(batches)}.")
        zdb.init_batches(app_name, [str(item) for item in list(batches)])

    return success_response(data={}, message="The batch is received successfully.")


@node_blueprint.route("/<string:app_name>/batches", methods=["PUT"])
@utils.validate_request
@utils.not_sequencer
def put_batches(app_name: str) -> Response:
    """Put a new batch into the database."""
    if not app_name:
        return error_response(ErrorCodes.INVALID_REQUEST, "app_name is required")
    if app_name not in list(zconfig.APPS):
        return error_response(ErrorCodes.INVALID_REQUEST, "Invalid app name.")
    data = request.data.decode('latin-1')
    zlogger.info(f"The batch is added. app: {app_name}, data length: {len(data)}.")
    zdb.init_batches(app_name, [data])
    return success_response(data={}, message="The batch is received successfully.")

@node_blueprint.route("/sign_sync_point", methods=["POST"])
@utils.validate_request
@utils.not_sequencer
def post_sign_sync_point() -> Response:
    """Sign a batch."""
    # TODO: only the sequencer should be able to call this route
    req_data: dict[str, Any] = request.get_json(silent=True) or {}
    required_keys: list[str] = [
        "app_name", "state", "index", "hash", "chaining_hash"
    ]
    error_message: str = utils.validate_keys(req_data, required_keys)
    if error_message:
        return error_response(ErrorCodes.INVALID_REQUEST, error_message)
    req_data["signature"] = tasks.sign_sync_point(req_data)
    return success_response(data=req_data)


@node_blueprint.route("/dispute", methods=["POST"])
@utils.validate_request
@utils.not_sequencer
def post_dispute() -> Response:
    """Handle a dispute by initializing batches if required."""
    req_data: dict[str, Any] = request.get_json(silent=True) or {}
    required_keys: list[str] = [
        "sequencer_id", "apps_missed_batches", "is_sequencer_down", "timestamp"
    ]
    error_message: str = utils.validate_keys(req_data, required_keys)
    if error_message:
        return error_response(ErrorCodes.INVALID_REQUEST, error_message)
    if req_data["sequencer_id"] != zconfig.SEQUENCER["id"]:
        return error_response(ErrorCodes.INVALID_SEQUENCER)
    if zdb.has_missed_batches() or zdb.is_sequencer_down:
        timestamp: int = int(time.time())
        data: dict[str, Any] = {
            "node_id": zconfig.NODE["id"],
            "old_sequencer_id": zconfig.SEQUENCER["id"],
            "new_sequencer_id": utils.get_next_sequencer_id(zconfig.SEQUENCER["id"]),
            "timestamp": timestamp,
            "signature": utils.eth_sign(f'{zconfig.SEQUENCER["id"]}{timestamp}'),
        }
        return success_response(data=data)

    for app_name, missed_batches in req_data["apps_missed_batches"].items():
        batches = [batch["body"] for batch in missed_batches.values()]
        zdb.init_batches(app_name, batches)
    return error_response(ErrorCodes.ISSUE_NOT_FOUND)


@node_blueprint.route("/switch", methods=["POST"])
@utils.validate_request
def post_switch_sequencer() -> Response:
    """Switch the sequencer based on the provided proofs."""
    req_data: dict[str, Any] = request.get_json(silent=True) or {}
    required_keys: list[str] = ["timestamp", "proofs"]
    error_message: str = utils.validate_keys(req_data, required_keys)
    if error_message:
        return error_response(ErrorCodes.INVALID_REQUEST, error_message)
    if utils.is_switch_approved(req_data["proofs"]):
        zdb.pause_node.set()
        old_sequencer_id, new_sequencer_id = utils.get_switch_parameter_from_proofs(
            req_data["proofs"]
        )
        tasks.switch_sequencer(old_sequencer_id, new_sequencer_id)
        return success_response(data={})

    return error_response(ErrorCodes.SEQUENCER_CHANGE_NOT_APPROVED)


@node_blueprint.route("/state", methods=["GET"])
@utils.validate_request
def get_state() -> Response:
    """Get the state of the node and its apps."""
    data: dict[str, Any] = {
        "sequencer": zconfig.NODE["id"] == zconfig.SEQUENCER["id"],
        "version": zconfig.VERSION,
        "sequencer_id": zconfig.SEQUENCER["id"],
        "node_id": zconfig.NODE["id"],
        "public_key_g2": zconfig.NODE["public_key_g2"].getStr(10).decode('utf-8'),
        "address": zconfig.NODE["address"],
        "apps": {},
    }

    for app_name in list(zconfig.APPS.keys()):
        last_sequenced_batch_record = zdb.get_last_operational_batch_record_or_empty(app_name, "sequenced")
        last_locked_batch_record = zdb.get_last_operational_batch_record_or_empty(app_name, "locked")
        last_finalized_batch_record = zdb.get_last_operational_batch_record_or_empty(app_name, "finalized")

        data['apps'][app_name] = {
            "last_sequenced_index": last_sequenced_batch_record.get("index", 0),
            "last_sequenced_hash": last_sequenced_batch_record.get("payload", {}).get("hash", ""),
            "last_locked_index": last_locked_batch_record.get("index", 0),
            "last_locked_hash": last_locked_batch_record.get("payload", {}).get("hash", ""),
            "last_finalized_index": last_finalized_batch_record.get("index", 0),
            "last_finalized_hash": last_finalized_batch_record.get("payload", {}).get("hash", ""),
        }
    return success_response(data=data)


@node_blueprint.route("/<string:app_name>/batches/finalized/last", methods=["GET"])
@utils.validate_request
def get_last_finalized_batch(app_name: str) -> Response:
    """Get the last finalized batch record for a given app."""
    if app_name not in list(zconfig.APPS):
        return error_response(ErrorCodes.INVALID_REQUEST, "Invalid app name.")
    last_finalized_batch_record = zdb.get_last_operational_batch_record_or_empty(app_name, "finalized")
    return success_response(
        data=batch_record_to_stateful_batch(last_finalized_batch_record)
    )


@node_blueprint.route("/<string:app_name>/batches/<string:state>", methods=["GET"])
@utils.validate_request
def get_batches(app_name: str, state: str) -> Response:
    """Get batches for a given app and states."""
    if app_name not in list(zconfig.APPS):
        return error_response(ErrorCodes.INVALID_REQUEST, "Invalid app name.")
    after: int = request.args.get("after", default=0, type=int)

    if after < 0:
        return error_response(ErrorCodes.INVALID_REQUEST, "Invalid after param.")

    batch_sequence = zdb.get_global_operational_batch_sequence(app_name, state, after)
    if not batch_sequence:
        return success_response(data=None)

    for i, batch_record in enumerate(batch_sequence.records()):
        assert batch_record["index"] == after + i + 1, \
            f'error in getting batches: {batch_record["index"]} != {after + i + 1}, {i}, {[batch_record["index"] for batch_record in batch_sequence.records()]}\n{zdb.apps[app_name]["operational_batch_sequence"]}'

    first_chaining_hash: str = batch_sequence.get_first_or_empty()["payload"]["chaining_hash"]

    finalized = {}
    for batch_record in reversed(batch_sequence.records()):
        if "finalization_signature" in batch_record:
            for k in ("finalization_signature", "hash", "chaining_hash"):
                finalized[k] = batch_record["payload"][k]
            finalized["nonsigners"] = batch_record["payload"]["finalized_nonsigners"]
            finalized["index"] = batch_record["index"]
            break

    return success_response(
        data={
            "batches": [batch["body"] for batch in batch_sequence.payloads()],
            "first_chaining_hash": first_chaining_hash,
            "finalized": finalized,
        }
    )
