"""This module defines the FastAPI router for node."""

import asyncio
import time

from fastapi import APIRouter, Depends, Query

from common import auth, bls, utils
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
    BatchesLimitExceededError,
    BatchSizeExceededError,
    InvalidRequestError,
    InvalidSequencerError,
    InvalidTimestampError,
    IsNotPostingNodeError,
    IsSequencerError,
    IssueNotFoundError,
    SequencerChangeNotApprovedError,
)
from common.logger import zlogger
from config import zconfig
from node import switch, tasks
from node.rate_limit import try_acquire_rate_limit_of_self_node
from settings import MODE_PROD

router = APIRouter()


@router.put(
    "/batches",
    dependencies=[
        Depends(utils.validate_version("node")),
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

        if not zconfig.is_sequencer:
            zdb.init_batch_bodies(app_name, valid_batches)
        else:
            if not try_acquire_rate_limit_of_self_node(valid_batches):
                raise BatchesLimitExceededError()
            zdb.sequencer_init_batch_bodies(app_name, valid_batches)

        zlogger.info(
            f"The batches are added. app: {app_name}, number of batches: {len(valid_batches)}."
        )

    return EmptyResponse(message="The batches are received successfully.")


@router.put(
    "/{app_name}/batches",
    dependencies=[
        Depends(utils.validate_version("node")),
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

    if not zconfig.is_sequencer:
        zdb.init_batch_bodies(app_name, [data])
    else:
        if not try_acquire_rate_limit_of_self_node([data]):
            raise BatchesLimitExceededError()
        zdb.sequencer_init_batch_bodies(app_name, [data])

    zlogger.info(f"The batch is added. app: {app_name}, data length: {len(data)}.")

    return EmptyResponse(message="The batch is received successfully.")


@router.post(
    "/sign_sync_point",
    dependencies=[
        Depends(utils.validate_version("node")),
        Depends(utils.not_sequencer),
        Depends(utils.is_synced),
        Depends(auth.verify_sequencer_access),
    ],
)
async def post_sign_sync_point(request: SignSyncPointRequest) -> SignSyncPointResponse:
    """Sign a synchronization point to contribute to batch consensus.

    This endpoint can only be called by the current active sequencer."""
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
        Depends(utils.is_synced),
        Depends(auth.verify_node_access),
    ],
)
async def post_dispute(request: DisputeRequest) -> DisputeResponse:
    """Report a dispute about sequencer issues and receive a signed confirmation."""
    if zconfig.is_sequencer and request.sequencer_id == zconfig.NODE["id"]:
        # Reject the dispute if the node is sequencer and the dispute is against it
        raise IssueNotFoundError()

    if (
        not zconfig.is_sequencer
        and request.sequencer_id == zconfig.SEQUENCER["id"]
        and not (
            zdb.is_sequencer_censoring()
            or zdb.has_delayed_batches()
            or zdb.is_sequencer_down
        )
    ):
        # Reject the dispute if the node is not sequencer and the dispute is against its sequencer
        # while it doesn't have any issues with its sequencer
        raise IssueNotFoundError()

    if not zconfig.is_sequencer:
        # Init other nodes censored batches to either face problem with the sequencer if
        # it's really censoring or relay the batches other nodes faced problem relaying
        for app_name, batch in request.apps_censored_batches.items():
            zdb.init_batch_bodies(app_name, [batch])

    now = int(time.time())
    if not (now - 5 <= request.timestamp <= now + 5):
        raise InvalidTimestampError()

    message = utils.gen_hash(f"{request.sequencer_id}{request.timestamp}")
    signature = bls.bls_sign(message)

    response_data = DisputeData(
        signature=signature,
    )

    return DisputeResponse(data=response_data)


@router.post(
    "/switch",
    dependencies=[
        Depends(utils.not_paused),
        Depends(utils.validate_version("node")),
        Depends(auth.verify_node_access),
    ],
)
async def post_switch_sequencer(request: SwitchRequest) -> EmptyResponse:
    """Initiate a sequencer switch based on provided signatures."""
    proofs = request.proofs

    if not switch.is_switch_approved(proofs):
        raise SequencerChangeNotApprovedError()

    old_sequencer_id = proofs[0].sequencer_id
    if old_sequencer_id != zconfig.SEQUENCER["id"]:
        raise InvalidSequencerError()

    new_sequencer_id = switch.get_next_sequencer_id(old_sequencer_id)
    zlogger.info(
        f"switch request received {zconfig.NODES[old_sequencer_id]['socket']} -> {zconfig.NODES[new_sequencer_id]['socket']}."
    )
    asyncio.create_task(switch.switch_to_sequencer(new_sequencer_id))

    return EmptyResponse(message="Sequencer switch initiated successfully.")


@router.get(
    "/state",
    dependencies=[
        Depends(utils.validate_version("node")),
    ],
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
    dependencies=[
        Depends(utils.validate_version("node")),
    ],
)
async def get_last_batch_by_state(app_name: str, state: str) -> GetAppLastBatchResponse:
    """Get the latest batch for a specific application in the given state."""
    if app_name not in zconfig.APPS:
        raise InvalidRequestError("Invalid app name.")

    if state not in {"locked", "finalized"}:
        raise InvalidRequestError("Invalid state. Must be 'locked' or 'finalized'.")

    last_batch_record = zdb.get_last_operational_batch_record_or_empty(app_name, state)

    if last_batch_record:
        stateful_batch_dict = batch_record_to_stateful_batch(
            app_name, last_batch_record
        )
        stateful_batch = StatefulBatch.from_typed_dict(stateful_batch_dict)
        return GetAppLastBatchResponse(data=stateful_batch)
    else:
        return GetAppLastBatchResponse(data=None)


@router.get(
    "/batches/{state}/last",
    dependencies=[
        Depends(utils.validate_version("node")),
    ],
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
    dependencies=[
        Depends(utils.validate_version("node")),
    ],
)
async def get_batches(
    app_name: str, state: str, after: int = Query(0, ge=0)
) -> GetBatchesResponse:
    """Retrieve batches for an application with pagination support."""
    if app_name not in zconfig.APPS:
        raise InvalidRequestError("Invalid app name.")

    batch_sequence = await zdb.get_global_operational_batch_sequence(
        app_name, state, after
    )

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
