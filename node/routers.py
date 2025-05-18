"""This module defines the FastAPI router for node."""

import threading
import time
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from common import utils
from common.batch import batch_record_to_stateful_batch
from common.db import zdb
from common.errors import (
    BatchSizeExceeded,
    InvalidRequest,
    InvalidSequencer,
    IsNotPostingNode,
    IsSequencer,
    IssueNotFound,
    SequencerChangeNotApproved,
)
from common.logger import zlogger
from common.response_utils import success_response
from config import zconfig
from node import switch, tasks
from settings import MODE_PROD

router = APIRouter()


@router.put(
    "/batches",
    dependencies=[
        Depends(utils.validate_version("node")),
        Depends(utils.not_sequencer),
        Depends(utils.is_synced),
        Depends(utils.not_paused),
    ],
)
async def put_bulk_batches(request: Request) -> JSONResponse:
    if "posting" not in zconfig.NODE["roles"]:
        raise IsNotPostingNode()

    batches_mapping = await request.json()
    valid_apps = set(zconfig.APPS)
    filtered_batches_mapping = {
        app_name: batches
        for app_name, batches in batches_mapping.items()
        if app_name in valid_apps
    }

    for app_name, batches in filtered_batches_mapping.items():
        valid_batches = [
            str(item)
            for item in list(batches)
            if utils.get_utf8_size_kb(str(item)) <= zconfig.MAX_BATCH_SIZE_KB
        ]
        zlogger.info(
            f"The batches are going to be initialized. app: {app_name}, number of batches: {len(valid_batches)}."
        )
        zdb.init_batches(app_name, valid_batches)

    return success_response(data={}, message="The batch is received successfully.")


@router.put(
    "/{app_name}/batches",
    dependencies=[
        Depends(utils.validate_version("node")),
        Depends(utils.not_sequencer),
        Depends(utils.is_synced),
        Depends(utils.not_paused),
    ],
)
async def put_batches(app_name: str, request: Request) -> JSONResponse:
    if "posting" not in zconfig.NODE["roles"]:
        raise IsNotPostingNode()

    if not app_name:
        raise InvalidRequest("app_name is required.")

    if app_name not in list(zconfig.APPS):
        raise InvalidRequest(f"Invalid app name: {app_name}.")

    # Read raw body bytes, decode Latin-1
    body_bytes = await request.body()
    data = body_bytes.decode("latin-1")

    if utils.get_utf8_size_kb(data) > zconfig.MAX_BATCH_SIZE_KB:
        raise BatchSizeExceeded()

    zlogger.info(f"The batch is added. app: {app_name}, data length: {len(data)}.")
    zdb.init_batches(app_name, [data])
    return success_response(data={}, message="The batch is received successfully.")


@router.post(
    "/sign_sync_point",
    dependencies=[
        Depends(utils.validate_version("node")),
        Depends(utils.not_sequencer),
        Depends(utils.is_synced),
        Depends(
            utils.validate_body_keys(
                required_keys=["app_name", "state", "index", "hash", "chaining_hash"]
            )
        ),
    ],
)
async def post_sign_sync_point(request: Request) -> JSONResponse:
    req_data: dict[str, Any] = await request.json()

    # TODO: only the sequencer should be able to call this route
    req_data["signature"] = tasks.sign_sync_point(req_data)
    return success_response(data=req_data)


@router.post(
    "/dispute",
    dependencies=[
        Depends(utils.validate_version("node")),
        Depends(utils.not_sequencer),
        Depends(utils.is_synced),
        Depends(
            utils.validate_body_keys(
                required_keys=[
                    "sequencer_id",
                    "apps_missed_batches",
                    "is_sequencer_down",
                    "timestamp",
                ]
            )
        ),
    ],
)
async def post_dispute(request: Request) -> JSONResponse:
    req_data: dict[str, Any] = await request.json()

    if req_data["sequencer_id"] != zconfig.SEQUENCER["id"]:
        raise InvalidSequencer()

    if zdb.has_missed_batches() or zdb.has_delayed_batches() or zdb.is_sequencer_down:
        timestamp: int = int(time.time())
        data: dict[str, Any] = {
            "node_id": zconfig.NODE["id"],
            "old_sequencer_id": zconfig.SEQUENCER["id"],
            "new_sequencer_id": utils.get_next_sequencer_id(zconfig.SEQUENCER["id"]),
            "timestamp": timestamp,
            "signature": utils.eth_sign(f"{zconfig.SEQUENCER['id']}{timestamp}"),
        }
        return success_response(data=data)

    # fixme: why init missed batches here?
    for app_name, missed_batches in req_data["apps_missed_batches"].items():
        batches = [batch["body"] for batch in missed_batches.values()]
        zdb.init_batches(app_name, batches)

    raise IssueNotFound()


@router.post(
    "/switch",
    dependencies=[
        Depends(utils.validate_version("node")),
        Depends(utils.validate_body_keys(required_keys=["timestamp", "proofs"])),
    ],
)
async def post_switch_sequencer(request: Request) -> JSONResponse:
    req_data: dict[str, Any] = await request.json()
    proofs = req_data["proofs"]

    if not utils.is_switch_approved(proofs):
        raise SequencerChangeNotApproved()

    old_sequencer_id, new_sequencer_id = utils.get_switch_parameter_from_proofs(proofs)

    def run_switch_sequencer() -> None:
        switch.switch_sequencer(old_sequencer_id, new_sequencer_id)

    zlogger.info(
        f"switch request received {zconfig.NODES[old_sequencer_id]['socket']} -> {zconfig.NODES[new_sequencer_id]['socket']}."
    )
    threading.Thread(target=run_switch_sequencer).start()

    return success_response(data={})


@router.get("/state")
async def get_state() -> JSONResponse:
    if (
        zconfig.get_mode() == MODE_PROD
        and zconfig.NODE["id"] == zconfig.SEQUENCER["id"]
    ):
        raise IsSequencer()

    data: dict[str, Any] = {
        "sequencer": zconfig.NODE["id"] == zconfig.SEQUENCER["id"],
        "version": zconfig.VERSION,
        "sequencer_id": zconfig.SEQUENCER["id"],
        "node_id": zconfig.NODE["id"],
        "pubkeyG2_X": zconfig.NODE["pubkeyG2_X"],
        "pubkeyG2_Y": zconfig.NODE["pubkeyG2_Y"],
        "address": zconfig.NODE["address"],
        "apps": {},
    }

    for app_name in list(zconfig.APPS.keys()):
        last_sequenced_batch_record = zdb.get_last_operational_batch_record_or_empty(
            app_name, "sequenced"
        )
        last_locked_batch_record = zdb.get_last_operational_batch_record_or_empty(
            app_name, "locked"
        )
        last_finalized_batch_record = zdb.get_last_operational_batch_record_or_empty(
            app_name, "finalized"
        )

        data["apps"][app_name] = {
            "last_sequenced_index": last_sequenced_batch_record.get("index", 0),
            "last_sequenced_hash": last_sequenced_batch_record.get("batch", {}).get(
                "hash", ""
            ),
            "last_locked_index": last_locked_batch_record.get("index", 0),
            "last_locked_hash": last_locked_batch_record.get("batch", {}).get(
                "hash", ""
            ),
            "last_finalized_index": last_finalized_batch_record.get("index", 0),
            "last_finalized_hash": last_finalized_batch_record.get("batch", {}).get(
                "hash", ""
            ),
        }

    return success_response(data=data)


@router.get(
    "/{app_name}/batches/{state}/last",
    dependencies=[Depends(utils.validate_version("node"))],
)
async def get_last_batch_by_state(app_name: str, state: str) -> JSONResponse:
    if app_name not in zconfig.APPS:
        raise InvalidRequest("Invalid app name.")

    if state not in {"locked", "finalized"}:
        raise InvalidRequest("Invalid state. Must be 'locked' or 'finalized'.")

    last_batch_record = zdb.get_last_operational_batch_record_or_empty(app_name, state)
    return success_response(data=batch_record_to_stateful_batch(last_batch_record))


@router.get(
    "/batches/{state}/last", dependencies=[Depends(utils.validate_version("node"))]
)
async def get_last_batches_in_bulk_mode(state: str) -> JSONResponse:
    if state not in {"locked", "finalized"}:
        raise InvalidRequest("Invalid state. Must be 'locked' or 'finalized'.")

    last_batch_records = {
        app_name: batch_record_to_stateful_batch(
            zdb.get_last_operational_batch_record_or_empty(app_name, state)
        )
        for app_name in zconfig.APPS
    }
    return success_response(data=last_batch_records)


@router.get(
    "/{app_name}/batches/{state}",
    dependencies=[Depends(utils.validate_version("node"))],
)
async def get_batches(
    app_name: str, state: str, after: int = Query(0, ge=0)
) -> JSONResponse:
    if app_name not in zconfig.APPS:
        raise InvalidRequest("Invalid app name.")

    batch_sequence = zdb.get_global_operational_batch_sequence(app_name, state, after)
    if not batch_sequence:
        return success_response(data=None)

    for i, batch_record in enumerate(batch_sequence.records()):
        assert batch_record["index"] == after + i + 1, (
            f"error in getting batches: {batch_record['index']} != {after + i + 1}, {i}, "
            f"{[batch_record['index'] for batch_record in batch_sequence.records()]}\n"
            f"{zdb.apps[app_name]['operational_batch_sequence']}"
        )

    first_chaining_hash = batch_sequence.get_first_or_empty()["batch"]["chaining_hash"]

    finalized = next(
        (
            {
                "signature": b["batch"]["finalization_signature"],
                "hash": b["batch"]["hash"],
                "chaining_hash": b["batch"]["chaining_hash"],
                "nonsigners": b["batch"]["finalized_nonsigners"],
                "index": b["index"],
                "tag": b["batch"]["finalized_tag"],
            }
            for b in batch_sequence.records(reverse=True)
            if "finalization_signature" in b["batch"]
        ),
        {},
    )

    locked = next(
        (
            {
                "signature": b["batch"]["lock_signature"],
                "hash": b["batch"]["hash"],
                "chaining_hash": b["batch"]["chaining_hash"],
                "nonsigners": b["batch"]["locked_nonsigners"],
                "index": b["index"],
                "tag": b["batch"]["locked_tag"],
            }
            for b in batch_sequence.records(reverse=True)
            if "lock_signature" in b["batch"]
        ),
        {},
    )

    return success_response(
        data={
            "batches": [b["body"] for b in batch_sequence.batches()],
            "first_chaining_hash": first_chaining_hash,
            "finalized": finalized,
            "locked": locked,
        }
    )
