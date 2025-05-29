"""This module defines the FastAPI router for sequencer."""

from fastapi import APIRouter, Depends

from common import utils
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
        Depends(utils.sequencer_only),
        Depends(utils.not_paused),
        Depends(utils.validate_version("sequencer")),
    ],
)
async def put_batches(
    request: SequencerPutBatchesRequest,
) -> SequencerPutBatchesResponse:
    """Submit batches to the sequencer for ordering and consensus."""
    # Check rate limits
    if not try_acquire_rate_limit_of_other_nodes(
        node_id=request.node_id, batches=request.batches
    ):
        raise BatchesLimitExceededError()
    # Validate batch sizes
    for batch in request.batches:
        if utils.get_utf8_size_kb(batch) > zconfig.MAX_BATCH_SIZE_KB:
            raise BatchSizeExceededError()

    # Verify signature
    concat_hash = "".join(utils.gen_hash(batch) for batch in request.batches)
    is_eth_sig_verified = utils.is_eth_sig_verified(
        signature=request.signature,
        node_id=request.node_id,
        message=concat_hash,
    )
    if not is_eth_sig_verified:
        raise PermissionDeniedError(f"the sig on the {request=} can not be verified.")
    if str(request.node_id) not in zconfig.last_state.posting_nodes:
        raise PermissionDeniedError(f"{request.node_id} is not a posting node.")
    if request.app_name not in zconfig.APPS:
        raise InvalidRequestError(f"{request.app_name} is not a valid app name.")
    response_data = _put_batches(request)
    return SequencerPutBatchesResponse(data=response_data)


def _put_batches(
    request: SequencerPutBatchesRequest,
) -> SequencerPutBatchesResponseData:
    """Process the batches data and return a structured response."""
    zdb.sequencer_init_batch_bodies(
        app_name=request.app_name,
        batch_bodies=request.batches,
    )
    batch_sequence = zdb.get_global_operational_batch_sequence(
        app_name=request.app_name,
        after=request.sequenced_index,
    )
    last_finalized_batch_record = zdb.get_last_operational_batch_record_or_empty(
        app_name=request.app_name,
        state="finalized",
    )
    last_finalized_index = last_finalized_batch_record.get("index", 0)
    last_locked_batch_record = zdb.get_last_operational_batch_record_or_empty(
        app_name=request.app_name,
        state="locked",
    )
    if batch_sequence:
        if batch_sequence.get_last_or_empty()[
            "index"
        ] < last_finalized_batch_record.get("index", 0):
            last_finalized_batch_record = next(
                (
                    d
                    for d in batch_sequence.records(reverse=True)
                    if "finalization_signature" in d["batch"]
                ),
                {},
            )
        if batch_sequence.get_last_or_empty()["index"] < last_locked_batch_record.get(
            "index",
            0,
        ):
            last_locked_batch_record = next(
                (
                    d
                    for d in batch_sequence.records(reverse=True)
                    if "lock_signature" in d["batch"]
                ),
                {},
            )
    zdb.upsert_node_state(
        {
            "app_name": request.app_name,
            "node_id": request.node_id,
            "sequenced_index": request.sequenced_index,
            "sequenced_chaining_hash": request.sequenced_chaining_hash,
            "locked_index": request.locked_index,
            "locked_chaining_hash": request.locked_chaining_hash,
        },
    )

    last_finalized_batch = last_finalized_batch_record.get("batch", {})
    last_locked_batch = last_locked_batch_record.get("batch", {})

    return SequencerPutBatchesResponseData(
        batches=[batch["body"] for batch in batch_sequence.batches()],
        last_finalized_index=last_finalized_index,
        finalized=BatchSignatureInfo(
            index=last_finalized_batch_record.get("index", 0),
            chaining_hash=last_finalized_batch.get("chaining_hash", ""),
            signature=last_finalized_batch.get("finalization_signature", ""),
            nonsigners=last_finalized_batch.get("finalized_nonsigners", []),
            tag=last_finalized_batch.get("finalized_tag", 0),
        ),
        locked=BatchSignatureInfo(
            index=last_locked_batch_record.get("index", 0),
            chaining_hash=last_locked_batch.get("chaining_hash", ""),
            signature=last_locked_batch.get("lock_signature", ""),
            nonsigners=last_locked_batch.get("locked_nonsigners", []),
            tag=last_locked_batch.get("locked_tag", 0),
        ),
    )
