"""This module defines the Flask blueprint for node-related routes."""

import time
from typing import Any

from flask import Blueprint, Response, request

from common import utils
from common.batch import batch_record_to_stateful_batch
from common.db import zdb
from common.errors import ErrorCodes
from common.logger import zlogger
from common.response_utils import error_response, success_response
from config import zconfig
from settings import MODE_PROD
from common.utils import errors, response_utils
from . import tasks

node_blueprint = Blueprint("node", __name__)


@node_blueprint.route("/batches", methods=["PUT"])
@utils.not_synced
@utils.validate_version
@utils.not_sequencer
def put_bulk_batches() -> Response:
    """Put a new batch into the database."""
    batches_mapping = request.get_json()
    valid_apps = set(zconfig.APPS)
    filtered_batches_mapping = {
        app_name: batches
        for app_name, batches in batches_mapping.items()
        if app_name in valid_apps
    }

    for app_name, batches in filtered_batches_mapping.items():
        zlogger.info(f"The batches are going to be initialized. app: {app_name}, number of batches: {len(batches)}.")
        zdb.init_batches(app_name, [str(item) for item in list(batches)])

    return success_response(data={}, message="The batch is received successfully.")


@node_blueprint.route("/<string:app_name>/batches", methods=["PUT"])
@utils.not_synced
@utils.validate_version
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
@utils.validate_version
@utils.validate_body_keys(required_keys=["app_name", "state", "index", "hash", "chaining_hash"])
@utils.not_sequencer
def post_sign_sync_point() -> Response:
    """Sign a batch."""
    # TODO: only the sequencer should be able to call this route
    req_data: dict[str, Any] = request.get_json(silent=True) or {}

    req_data["signature"] = tasks.sign_sync_point(req_data)
    return success_response(data=req_data)


@node_blueprint.route("/dispute", methods=["POST"])
@utils.validate_version
@utils.validate_body_keys(required_keys=["sequencer_id", "apps_missed_batches", "is_sequencer_down", "timestamp"])
@utils.not_sequencer
def post_dispute() -> Response:
    """Handle a dispute by initializing batches if required."""
    req_data: dict[str, Any] = request.get_json(silent=True) or {}

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
@utils.validate_version
@utils.validate_body_keys(required_keys=["timestamp", "proofs"])
def post_switch_sequencer() -> Response:
    """Switch the sequencer based on the provided proofs."""
    req_data: dict[str, Any] = request.get_json(silent=True) or {}
    if utils.is_switch_approved(req_data["proofs"]):
        zdb.pause_node.set()
        old_sequencer_id, new_sequencer_id = utils.get_switch_parameter_from_proofs(
            req_data["proofs"]
        )
        tasks.switch_sequencer(old_sequencer_id, new_sequencer_id)
        return success_response(data={})

    return error_response(ErrorCodes.SEQUENCER_CHANGE_NOT_APPROVED)


@node_blueprint.route("/state", methods=["GET"])
@utils.conditional_decorator(condition=lambda: (zconfig.get_mode() == MODE_PROD), decorator=utils.not_sequencer)
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
            "last_sequenced_hash": last_sequenced_batch_record.get("batch", {}).get("hash", ""),
            "last_locked_index": last_locked_batch_record.get("index", 0),
            "last_locked_hash": last_locked_batch_record.get("batch", {}).get("hash", ""),
            "last_finalized_index": last_finalized_batch_record.get("index", 0),
            "last_finalized_hash": last_finalized_batch_record.get("batch", {}).get("hash", ""),
        }
    return success_response(data=data)


@node_blueprint.route("/<string:app_name>/batches/finalized/last", methods=["GET"])
@utils.validate_version
def get_last_finalized_batch(app_name: str) -> Response:
    """Get the last finalized batch record for a given app."""
    if app_name not in list(zconfig.APPS):
        return error_response(ErrorCodes.INVALID_REQUEST, "Invalid app name.")
    last_finalized_batch_record = zdb.get_last_operational_batch_record_or_empty(app_name, "finalized")
    return success_response(
        data=batch_record_to_stateful_batch(last_finalized_batch_record)
    )


@node_blueprint.route("/<string:app_name>/batches/<string:state>", methods=["GET"])
@utils.validate_version
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

    first_chaining_hash = batch_sequence.get_first_or_empty()["batch"]["chaining_hash"]

    finalized = next(
        (
            {
                "finalization_signature": batch_record["batch"]["finalization_signature"],
                "hash": batch_record["batch"]["hash"],
                "chaining_hash": batch_record["batch"]["chaining_hash"],
                "nonsigners": batch_record["batch"]["finalized_nonsigners"],
                "index": batch_record["index"],
            }
            for batch_record in batch_sequence.records(reverse=True)
            if "finalization_signature" in batch_record["batch"]
        ),
        {}
    )

    return success_response(
        data={
            "batches": [batch["body"] for batch in batch_sequence.batches()],
            "first_chaining_hash": first_chaining_hash,
            "finalized": finalized,
        }
    )
