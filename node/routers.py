"""This module defines the FastAPI router for node."""

import threading
import time

from fastapi import APIRouter, Depends, Query

from common import utils
from common.api_models import (
    AppState,
    BatchSignatureInfo,
    DisputeData,
    DisputeRequest,
    DisputeResponse,
    EmptyResponse,
    GetAppLastBatchResponse,
    GetAppsLastBatchResponse,
    GetBatchesData,
    GetBatchesResponse,
    NodePutBatchRequest,
    NodePutBulkBatchesRequest,
    NodeStateData,
    NodeStateResponse,
    SignSyncPointData,
    SignSyncPointRequest,
    SignSyncPointResponse,
    StatefulBatch,
    SwitchRequest,
)
from common.batch import batch_record_to_stateful_batch
from common.db import zdb
from common.errors import (
    BatchSizeExceededError,
    InvalidRequestError,
    InvalidSequencerError,
    IsNotPostingNodeError,
    IsSequencerError,
    IssueNotFoundError,
    SequencerChangeNotApprovedError,
)
from common.logger import zlogger
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
async def put_bulk_batches(request: NodePutBulkBatchesRequest) -> EmptyResponse:
    """Submit multiple batches for different applications in a single request."""
    if "posting" not in zconfig.NODE["roles"]:
        raise IsNotPostingNodeError()

    valid_apps = set(zconfig.APPS)
    filtered_batches_mapping = {
        app_name: batches
        for app_name, batches in request.root.items()
        if app_name in valid_apps
    }

    for app_name, batches in filtered_batches_mapping.items():
        valid_batches = [
            str(item)
            for item in batches
            if utils.get_utf8_size_kb(str(item)) <= zconfig.MAX_BATCH_SIZE_KB
        ]
        zlogger.info(
            f"The batches are going to be initialized. app: {app_name}, number of batches: {len(valid_batches)}."
        )
        zdb.init_batches(app_name, valid_batches)

    return EmptyResponse(message="The batches are received successfully.")


@router.put(
    "/{app_name}/batches",
    dependencies=[
        Depends(utils.validate_version("node")),
        Depends(utils.not_sequencer),
        Depends(utils.is_synced),
        Depends(utils.not_paused),
    ],
)
async def put_batches(app_name: str, request: NodePutBatchRequest) -> EmptyResponse:
    """Submit a batch to be sequenced for the specified application."""
    if "posting" not in zconfig.NODE["roles"]:
        raise IsNotPostingNodeError()

    if not app_name:
        raise InvalidRequestError("app_name is required.")

    if app_name not in list(zconfig.APPS):
        raise InvalidRequestError(f"Invalid app name: {app_name}.")

    data = request.root

    if utils.get_utf8_size_kb(data) > zconfig.MAX_BATCH_SIZE_KB:
        raise BatchSizeExceededError()

    zlogger.info(f"The batch is added. app: {app_name}, data length: {len(data)}.")
    zdb.init_batches(app_name, [data])

    return EmptyResponse(message="The batch is received successfully.")


@router.post(
    "/sign_sync_point",
    dependencies=[
        Depends(utils.validate_version("node")),
        Depends(utils.not_sequencer),
        Depends(utils.is_synced),
    ],
)
async def post_sign_sync_point(request: SignSyncPointRequest) -> SignSyncPointResponse:
    """Sign a synchronization point to contribute to batch consensus."""
    # TODO: only the sequencer should be able to call this route
    signature = tasks.sign_sync_point(
        {
            "app_name": request.app_name,
            "state": request.state,
            "index": request.index,
            "chaining_hash": request.chaining_hash,
        }
    )
    response_data = SignSyncPointData(
        app_name=request.app_name,
        state=request.state,
        index=request.index,
        chaining_hash=request.chaining_hash,
        signature=signature,
    )

    return SignSyncPointResponse(data=response_data)


@router.post(
    "/dispute",
    dependencies=[
        Depends(utils.validate_version("node")),
        Depends(utils.not_sequencer),
        Depends(utils.is_synced),
    ],
)
async def post_dispute(request: DisputeRequest) -> DisputeResponse:
    """Report a dispute about sequencer issues and receive a signed confirmation."""
    if request.sequencer_id != zconfig.SEQUENCER["id"]:
        raise InvalidSequencerError()

    for app_name, batch in request.apps_censored_batches.items():
        zdb.init_batches(app_name, [batch])

    if (
        zdb.is_sequencer_censoring()
        or zdb.has_delayed_batches()
        or zdb.is_sequencer_down
    ):
        timestamp = int(time.time())
        signature = utils.eth_sign(f"{zconfig.SEQUENCER['id']}{timestamp}")

        response_data = DisputeData(
            node_id=zconfig.NODE["id"],
            old_sequencer_id=zconfig.SEQUENCER["id"],
            new_sequencer_id=switch.get_next_sequencer_id(zconfig.SEQUENCER["id"]),
            timestamp=timestamp,
            signature=signature,
        )

        return DisputeResponse(data=response_data)

    raise IssueNotFoundError()


@router.post(
    "/switch",
    dependencies=[
        Depends(utils.validate_version("node")),
    ],
)
async def post_switch_sequencer(request: SwitchRequest) -> EmptyResponse:
    """Initiate a sequencer switch based on provided signatures."""
    proofs = request.proofs

    if not switch.is_switch_approved(proofs):
        raise SequencerChangeNotApprovedError()

    old_sequencer_id, new_sequencer_id = switch.get_switch_parameter_from_proofs(proofs)

    def run_switch_sequencer() -> None:
        switch.switch_sequencer(old_sequencer_id, new_sequencer_id)

    zlogger.info(
        f"switch request received {zconfig.NODES[old_sequencer_id]['socket']} -> {zconfig.NODES[new_sequencer_id]['socket']}."
    )
    threading.Thread(target=run_switch_sequencer).start()

    return EmptyResponse(message="Sequencer switch initiated successfully.")


@router.get(
    "/state",
)
async def get_state() -> NodeStateResponse:
    """Retrieve current node information and application status."""
    if (
        zconfig.get_mode() == MODE_PROD
        and zconfig.NODE["id"] == zconfig.SEQUENCER["id"]
    ):
        raise IsSequencerError()

    app_states = {}
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

        app_states[app_name] = AppState(
            last_sequenced_index=last_sequenced_batch_record.get("index", 0),
            last_locked_index=last_locked_batch_record.get("index", 0),
            last_finalized_index=last_finalized_batch_record.get("index", 0),
        )

    node_state = NodeStateData(
        sequencer=zconfig.NODE["id"] == zconfig.SEQUENCER["id"],
        version=zconfig.VERSION,
        sequencer_id=zconfig.SEQUENCER["id"],
        node_id=zconfig.NODE["id"],
        pubkeyG2_X=zconfig.NODE["pubkeyG2_X"],
        pubkeyG2_Y=zconfig.NODE["pubkeyG2_Y"],
        address=zconfig.NODE["address"],
        apps=app_states,
    )

    return NodeStateResponse(data=node_state)


@router.get(
    "/{app_name}/batches/{state}/last",
    dependencies=[Depends(utils.validate_version("node"))],
)
async def get_last_batch_by_state(app_name: str, state: str) -> GetAppLastBatchResponse:
    """Get the latest batch for a specific application in the given state."""
    if app_name not in zconfig.APPS:
        raise InvalidRequestError("Invalid app name.")

    if state not in {"locked", "finalized"}:
        raise InvalidRequestError("Invalid state. Must be 'locked' or 'finalized'.")

    last_batch_record = zdb.get_last_operational_batch_record_or_empty(app_name, state)
    stateful_batch_dict = batch_record_to_stateful_batch(last_batch_record)
    stateful_batch = StatefulBatch.from_typed_dict(stateful_batch_dict)

    return GetAppLastBatchResponse(data=stateful_batch)


@router.get(
    "/batches/{state}/last",
    dependencies=[Depends(utils.validate_version("node"))],
)
async def get_last_batches_in_bulk_mode(state: str) -> GetAppsLastBatchResponse:
    """Retrieve the latest batches for all applications in one request."""
    if state not in {"locked", "finalized"}:
        raise InvalidRequestError("Invalid state. Must be 'locked' or 'finalized'.")

    # Create a dictionary of app_name -> StatefulBatch (Pydantic models)
    last_batch_records = {}
    for app_name in zconfig.APPS:
        last_batch = zdb.get_last_operational_batch_record_or_empty(app_name, state)
        if last_batch:
            last_batch_records[app_name] = StatefulBatch.from_typed_dict(
                batch_record_to_stateful_batch(app_name, last_batch)
            )

    return GetAppsLastBatchResponse(data=last_batch_records)


@router.get(
    "/{app_name}/batches/{state}",
    dependencies=[Depends(utils.validate_version("node"))],
)
async def get_batches(
    app_name: str, state: str, after: int = Query(0, ge=0)
) -> GetBatchesResponse:
    """Retrieve batches for an application with pagination support."""
    if app_name not in zconfig.APPS:
        raise InvalidRequestError("Invalid app name.")

    batch_sequence = zdb.get_global_operational_batch_sequence(app_name, state, after)
    if not batch_sequence:
        return GetBatchesResponse(data=None)

    for i, batch_record in enumerate(batch_sequence.records()):
        assert batch_record["index"] == after + i + 1, (
            f"error in getting batches: {batch_record['index']} != {after + i + 1}, {i}, "
            f"{[batch_record['index'] for batch_record in batch_sequence.records()]}\n"
            f"{zdb.apps[app_name]['operational_batch_sequence']}"
        )

    first_chaining_hash = batch_sequence.get_first_or_empty()["batch"]["chaining_hash"]

    finalized = next(
        (
            BatchSignatureInfo(
                signature=b["batch"]["finalization_signature"],
                chaining_hash=b["batch"]["chaining_hash"],
                nonsigners=b["batch"]["finalized_nonsigners"],
                index=b["index"],
                tag=b["batch"]["finalized_tag"],
            )
            for b in batch_sequence.records(reverse=True)
            if b["batch"].get("finalization_signature")
        ),
        None,
    )

    locked = next(
        (
            BatchSignatureInfo(
                signature=b["batch"]["lock_signature"],
                chaining_hash=b["batch"]["chaining_hash"],
                nonsigners=b["batch"]["locked_nonsigners"],
                index=b["index"],
                tag=b["batch"]["locked_tag"],
            )
            for b in batch_sequence.records(reverse=True)
            if b["batch"].get("lock_signature")
        ),
        None,
    )

    response_data = GetBatchesData(
        batches=[b["body"] for b in batch_sequence.batches()],
        first_chaining_hash=first_chaining_hash,
        finalized=finalized,
        locked=locked,
    )

    return GetBatchesResponse(data=response_data)
