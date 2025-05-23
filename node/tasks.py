"""This module handles node tasks like sending batches of transactions, synchronization with the sequencer,
and other periodic node operations.
"""

import json
import random
import time
from typing import Any

import requests

from common import bls, utils
from common.batch_sequence import BatchSequence
from common.db import zdb
from common.errors import InvalidRequestError
from common.logger import zlogger
from common.state import is_state_before_or_equal
from config import zconfig
from node.rate_limit import (
    get_remaining_capacity_kb_of_self_node,
    try_acquire_rate_limit_of_self_node,
)


def send_batches() -> None:
    """Send batches for all apps."""
    single_iteration_apps_sync = True
    app_names = list(zconfig.APPS.keys())
    # shuffle apps to prevent starvation of later apps by earlier ones when limit is reaching
    random.shuffle(app_names)

    for app_name in app_names:
        finish_condition = send_app_batches_iteration(app_name=app_name)
        if finish_condition:
            continue

        single_iteration_apps_sync = False

        while True:
            finish_condition = send_app_batches_iteration(app_name=app_name)
            if finish_condition:
                break

    if single_iteration_apps_sync:
        zconfig.set_synced_flag()


def send_app_batches_iteration(app_name: str) -> bool:
    response = send_app_batches(app_name).get("data", {})
    sequencer_last_finalized_index = response.get(
        "last_finalized_index",
        BatchSequence.BEFORE_GLOBAL_INDEX_OFFSET,
    )
    last_in_memory_index = zdb.get_last_operational_batch_record_or_empty(
        app_name=app_name, state="sequenced"
    ).get("index", BatchSequence.BEFORE_GLOBAL_INDEX_OFFSET)
    if sequencer_last_finalized_index == BatchSequence.BEFORE_GLOBAL_INDEX_OFFSET:
        return True
    return sequencer_last_finalized_index <= last_in_memory_index


def send_app_batches(app_name: str) -> dict[str, Any]:
    """Send batches for a specific app."""
    max_size_kb = get_remaining_capacity_kb_of_self_node()
    initialized_batches: dict[str, Any] = zdb.get_limited_initialized_batch_map(
        app_name=app_name, max_size_kb=max_size_kb
    )
    batches = list(initialized_batches.values())

    last_sequenced_batch_record = zdb.get_last_operational_batch_record_or_empty(
        app_name=app_name,
        state="sequenced",
    )
    last_locked_batch_record = zdb.get_last_operational_batch_record_or_empty(
        app_name=app_name,
        state="locked",
    )

    concat_hash: str = "".join(initialized_batches.keys())
    concat_sig: str = utils.eth_sign(concat_hash)
    data: str = json.dumps(
        {
            "app_name": app_name,
            "batches": list(initialized_batches.values()),
            "node_id": zconfig.NODE["id"],
            "signature": concat_sig,
            "sequenced_index": last_sequenced_batch_record.get("index", 0),
            "sequenced_hash": last_sequenced_batch_record.get("batch", {}).get(
                "hash",
                "",
            ),
            "sequenced_chaining_hash": last_sequenced_batch_record.get("batch", {}).get(
                "chaining_hash",
                "",
            ),
            "locked_index": last_locked_batch_record.get("index", 0),
            "locked_hash": last_locked_batch_record.get("batch", {}).get("hash", ""),
            "locked_chaining_hash": last_locked_batch_record.get("batch", {}).get(
                "chaining_hash",
                "",
            ),
            "timestamp": int(time.time()),
        },
    )

    url: str = f"{zconfig.SEQUENCER['socket']}/sequencer/batches"
    response: dict[str, Any] = {}
    try:
        response = requests.put(url=url, data=data, headers=zconfig.HEADERS).json()
        response.raise_for_status()
        if response["status"] == "error":
            zlogger.warning(response["error"]["message"])
            zdb.add_missed_batches(app_name, initialized_batches.values())
            return {}

        try_acquire_rate_limit_of_self_node(batches)

        sequencer_resp = response["data"]
        censored_batches = sync_with_sequencer(
            app_name=app_name,
            initialized_batches=initialized_batches,
            sequencer_response=sequencer_resp,
        )
        zdb.is_sequencer_down = False
        if not censored_batches:
            zdb.clear_missed_batches(app_name)

    except Exception as e:
        zlogger.error(
            f"An unexpected error occurred, while sending batches to sequencer: {e=}, {response=}",
        )
        zdb.add_missed_batches(app_name, initialized_batches.values())
        zdb.is_sequencer_down = True

    return response


def sync_with_sequencer(
    app_name: str,
    initialized_batches: dict[str, Any],
    sequencer_response: dict[str, Any],
) -> dict[str, Any]:
    """Sync batches with the sequencer."""
    zdb.insert_sequenced_batches(
        app_name=app_name,
        batches=sequencer_response["batches"],
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

    return check_censorship(
        app_name=app_name,
        initialized_batches=initialized_batches,
        sequencer_response=sequencer_response,
    )


def check_censorship(
    app_name: str,
    initialized_batches: dict[str, Any],
    sequencer_response: dict[str, Any],
) -> dict[str, Any]:
    """Check for censorship and update missed batches."""
    sequenced_hashes: set[str] = set(
        batch["hash"] for batch in sequencer_response["batches"]
    )
    censored_batches: list[dict[str, Any]] = [
        batch
        for batch_hash, batch in initialized_batches.items()
        if batch_hash not in sequenced_hashes
    ]

    # remove sequenced batches from the missed batches dict
    missed_batches: list[dict[str, Any]] = [
        batch
        for batch_hash, batch in zdb.get_missed_batch_map(app_name).items()
        if batch_hash not in sequenced_hashes
    ]

    # add censored batches to the missed batches dict
    missed_batches += censored_batches

    zdb.set_missed_batches(app_name=app_name, missed_batches=missed_batches)
    return censored_batches


def sign_sync_point(sync_point: dict[str, Any]) -> str:
    """Confirm and sign the sync point"""
    batch_record = zdb.get_batch_record_by_hash_or_empty(
        sync_point["app_name"],
        sync_point["hash"],
    )
    batch = batch_record.get("batch", {})
    if (
        any(batch.get(key) != sync_point[key] for key in ["hash", "chaining_hash"])
        or not is_state_before_or_equal(sync_point["state"], batch_record["state"])
        or batch_record["index"] != sync_point["index"]
    ):
        raise InvalidRequestError(f"Invalid sync point. {sync_point=}, {batch_record=}")
    message: str = utils.gen_hash(json.dumps(sync_point, sort_keys=True))
    signature = bls.bls_sign(message)
    return signature
