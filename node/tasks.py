"""This module handles node tasks like sending batches of transactions, synchronization with the sequencer,
and other periodic node operations.
"""

import json
import random
import time
from typing import Any

from common import auth, bls, utils
from common.api_models import SequencerPutBatchesRequest
from common.batch_sequence import BatchSequence
from common.db import zdb
from common.errors import InvalidRequestError, IsNotSequencerError
from common.logger import zlogger
from common.sequencer_manager import zsequencer_manager
from common.state import is_state_before_or_equal
from config import zconfig
from node.rate_limit import (
    get_remaining_capacity_kb_of_self_node,
    try_acquire_rate_limit_of_self_node,
)


async def send_batches() -> None:
    """Send batches for all apps."""
    single_iteration_apps_sync = True
    app_names = list(zconfig.APPS.keys())
    # shuffle apps to prevent starvation of later apps by earlier ones when limit is reaching
    random.shuffle(app_names)

    for app_name in app_names:
        finish_condition = await send_app_batches_iteration(app_name=app_name)
        if finish_condition:
            continue

        single_iteration_apps_sync = False

        while True:
            finish_condition = await send_app_batches_iteration(app_name=app_name)
            if finish_condition:
                break

    if single_iteration_apps_sync:
        zconfig.set_synced_flag()


async def send_app_batches_iteration(app_name: str) -> bool:
    sequencer_last_finalized_index = await send_app_batches(app_name)
    last_in_memory_index = zdb.get_last_operational_batch_record_or_empty(
        app_name=app_name, state="sequenced"
    ).get("index", BatchSequence.BEFORE_GLOBAL_INDEX_OFFSET)
    if sequencer_last_finalized_index == BatchSequence.BEFORE_GLOBAL_INDEX_OFFSET:
        return True
    return sequencer_last_finalized_index <= last_in_memory_index


async def send_app_batches(app_name: str) -> int:
    """Send batches for a specific app and return sequencer last finalized index."""
    max_size_kb = get_remaining_capacity_kb_of_self_node()
    batch_bodies = zdb.pop_limited_initialized_batch_bodies(
        app_name=app_name, max_size_kb=max_size_kb
    )

    last_sequenced_batch_record = zdb.get_last_operational_batch_record_or_empty(
        app_name=app_name,
        state="sequenced",
    )
    last_locked_batch_record = zdb.get_last_operational_batch_record_or_empty(
        app_name=app_name,
        state="locked",
    )

    request = SequencerPutBatchesRequest(
        app_name=app_name,
        batches=batch_bodies,
        sequenced_index=last_sequenced_batch_record.get("index", 0),
        sequenced_chaining_hash=last_sequenced_batch_record.get("batch", {}).get(
            "chaining_hash",
            "",
        ),
        locked_index=last_locked_batch_record.get("index", 0),
        locked_chaining_hash=last_locked_batch_record.get("batch", {}).get(
            "chaining_hash",
            "",
        ),
        timestamp=int(time.time()),
    )

    url = f"{zconfig.SEQUENCER['socket']}/sequencer/batches"
    response = None
    try:
        async with auth.create_session() as session:
            async with session.put(
                url,
                json=request.model_dump(),
                timeout=5 if zconfig.is_synced else 30,
                raise_for_status=False,
            ) as r:
                response = await r.json()

        if response["status"] == "error":
            zlogger.warning(response["error"])
            zdb.reinit_missed_batch_bodies(app_name, batch_bodies)

            # This can happen if the node misses a switch request because of a reason like connectivity issues
            if response["error"]["code"] == IsNotSequencerError.__name__:
                await zsequencer_manager.reset_sequencer()

            zdb.is_sequencer_down = True
            return BatchSequence.BEFORE_GLOBAL_INDEX_OFFSET

        try_acquire_rate_limit_of_self_node(batch_bodies)

        sync_with_sequencer(
            app_name=app_name,
            sequencer_response=response["data"],
        )

        zdb.is_sequencer_down = False
        censored_batch_bodies = set(batch_bodies) - set(response["data"]["batches"])
        if censored_batch_bodies:
            zdb.reinit_missed_batch_bodies(app_name, censored_batch_bodies)
            zdb.set_sequencer_censoring(app_name)
        else:
            zdb.clear_sequencer_censoring(app_name)
        return response["data"]["last_finalized_index"]

    except Exception as e:
        zlogger.error(
            f"An unexpected error occurred, while sending batches to sequencer: {e=}, {response=}",
        )
        zdb.reinit_missed_batch_bodies(app_name, batch_bodies)
        zdb.is_sequencer_down = True
        return BatchSequence.BEFORE_GLOBAL_INDEX_OFFSET


def sync_with_sequencer(
    app_name: str,
    sequencer_response: dict[str, Any],
) -> None:
    """Sync batches with the sequencer."""
    zdb.insert_sequenced_batch_bodies(
        app_name=app_name,
        batch_bodies=sequencer_response["batches"],
    )
    last_locked_index = zdb.get_last_operational_batch_record_or_empty(
        app_name,
        "locked",
    ).get("index", 0)
    if sequencer_response["locked"]["index"] > last_locked_index:
        locking_result = zdb.lock_batches(
            app_name=app_name,
            signature_data=sequencer_response["locked"],
        )
        if not locking_result:
            zlogger.error("Invalid locking signature received from sequencer")

    last_finalized_index = zdb.get_last_operational_batch_record_or_empty(
        app_name,
        "finalized",
    ).get("index", 0)
    if sequencer_response["finalized"]["index"] > last_finalized_index:
        finalizing_result = zdb.finalize_batches(
            app_name=app_name,
            signature_data=sequencer_response["finalized"],
        )
        if not finalizing_result:
            zlogger.error("Invalid finalizing signature received from sequencer")

    current_time = int(time.time())
    for state in ("sequenced", "finalized"):
        index = zdb.get_last_operational_batch_record_or_empty(app_name, state).get(
            "index", BatchSequence.BEFORE_GLOBAL_INDEX_OFFSET
        )
        if index == BatchSequence.BEFORE_GLOBAL_INDEX_OFFSET:
            continue

        zdb.track_sequencing_indices(
            app_name=app_name, state=state, last_index=index, current_time=current_time
        )


def sign_sync_point(sync_point: dict[str, Any]) -> str:
    """Confirm and sign the sync point"""
    batch_record = zdb.get_batch_record_by_index_or_empty(
        sync_point["app_name"],
        sync_point["index"],
    )
    batch = batch_record.get("batch", {})
    if (
        batch.get("chaining_hash") != sync_point["chaining_hash"]
        or not is_state_before_or_equal(sync_point["state"], batch_record["state"])
        or batch_record["index"] != sync_point["index"]
    ):
        zlogger.debug(
            "Invalid sync point reasons: "
            f"{(batch.get("chaining_hash") != sync_point["chaining_hash"])=} "
            f"{(not is_state_before_or_equal(sync_point["state"], batch_record["state"]))=} "
            f"{(batch_record['index'] != sync_point['index'])=}"
        )
        raise InvalidRequestError(f"Invalid sync point. {sync_point=}, {batch_record=}")
    message = utils.gen_hash(json.dumps(sync_point, sort_keys=True))
    signature = bls.bls_sign(message)
    return signature
