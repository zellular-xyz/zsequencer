"""This module defines the FastAPI router for sequencer."""

import time

from fastapi import APIRouter, Depends, Header

from common import auth, utils
from common.api_models import (
    BatchSignatureInfo,
    SequencerPutBatchesRequest,
    SequencerPutBatchesResponse,
    SequencerPutBatchesResponseData,
)
from common.db import zdb
from common.errors import (
    BatchesLimitExceededError,
    BatchSizeExceededError,
    InvalidRequestError,
    PermissionDeniedError,
)
from config import zconfig
from sequencer.rate_limit import try_acquire_rate_limit_of_other_nodes

router = APIRouter()


@router.put(
    "/batches",
    dependencies=[
        Depends(utils.validate_version("sequencer")),
        Depends(auth.verify_node_access),
        Depends(utils.sequencer_only),
        Depends(utils.not_paused),
    ],
)
async def put_batches(
    request: SequencerPutBatchesRequest,
    signer: str | None = Header(None),
) -> SequencerPutBatchesResponse:
    """Submit batches to the sequencer for ordering and consensus."""
    node_id = signer
    # Check rate limits
    if not try_acquire_rate_limit_of_other_nodes(
        node_id=node_id, batch_bodies=request.batches
    ):
        raise BatchesLimitExceededError()
    # Validate batch sizes
    for batch in request.batches:
        if utils.get_utf8_size_kb(batch) > zconfig.MAX_BATCH_SIZE_KB:
            raise BatchSizeExceededError()

    if str(node_id) not in zconfig.last_state.posting_nodes:
        raise PermissionDeniedError(f"{node_id} is not a posting node.")
    if request.app_name not in zconfig.APPS:
        raise InvalidRequestError(f"{request.app_name} is not a valid app name.")

    response_data = await _put_batches(request, node_id)
    return SequencerPutBatchesResponse(data=response_data)


async def _put_batches(
    request: SequencerPutBatchesRequest,
    node_id: str,
) -> SequencerPutBatchesResponseData:
    """Process the batches data and return a structured response."""
    zdb.sequencer_init_batch_bodies(
        app_name=request.app_name,
        batch_bodies=request.batches,
    )

    batch_sequence = await zdb.get_global_operational_batch_sequence(
        app_name=request.app_name,
        after=request.sequenced_index,
    )

    last_locked_batch_record = zdb.get_last_operational_batch_record_or_empty(
        app_name=request.app_name,
        state="locked",
    )
    if last_locked_batch_record:
        last_locked_batch = last_locked_batch_record["batch"]
        last_locked_signature = BatchSignatureInfo(
            state="sequenced",
            index=last_locked_batch_record["index"],
            parent_index=last_locked_batch["locked_parent_index"],
            chaining_hash=last_locked_batch["chaining_hash"],
            signature=last_locked_batch["locked_signature"],
            nonsigners=last_locked_batch["locked_nonsigners"],
            tag=last_locked_batch["locked_tag"],
            timestamp=last_locked_batch["locked_timestamp"],
        )
    else:
        last_locked_signature = None

    last_finalized_batch_record = zdb.get_last_operational_batch_record_or_empty(
        app_name=request.app_name,
        state="finalized",
    )
    last_finalized_index = last_finalized_batch_record.get("index", 0)

    finalized_signatures = []
    next_index = (
        zdb.get_batch_record_by_index_or_empty(
            app_name=request.app_name, index=request.finalized_index or 1
        )
        .get("batch", {})
        .get("finalized_next_index")
    )
    while (
        next_index
        and next_index <= batch_sequence.get_last_index_or_default()
        and len(finalized_signatures) < 5
    ):
        batch = zdb.get_batch_record_by_index_or_empty(
            app_name=request.app_name, index=next_index
        )["batch"]
        signature_info = BatchSignatureInfo(
            state="locked",
            index=next_index,
            parent_index=batch["finalized_parent_index"],
            chaining_hash=batch["chaining_hash"],
            signature=batch["finalized_signature"],
            nonsigners=batch["finalized_nonsigners"],
            tag=batch["finalized_tag"],
            timestamp=batch["finalized_timestamp"],
        )
        finalized_signatures.append(signature_info)
        next_index = batch.get("finalized_next_index")

    zdb.upsert_node_state(
        {
            "app_name": request.app_name,
            "node_id": node_id,
            "sequenced_index": request.sequenced_index,
            "sequenced_chaining_hash": request.sequenced_chaining_hash,
            "locked_index": request.locked_index,
            "locked_chaining_hash": request.locked_chaining_hash,
            "update_timestamp": time.time(),
        },
    )

    return SequencerPutBatchesResponseData(
        batches=[batch["body"] for batch in batch_sequence.batches()],
        last_finalized_index=last_finalized_index,
        finalized_signatures=finalized_signatures,
        last_locked_signature=last_locked_signature,
    )
