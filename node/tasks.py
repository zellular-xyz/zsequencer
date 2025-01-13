"""
This module handles node tasks like sending batches of transactions, synchronization with the sequencer,
dispute handling, and switching sequencers.
"""

import asyncio
import json
import threading
import time
from typing import Any

import aiohttp
import requests
from eigensdk.crypto.bls import attestation
from typing import List
from historical_nodes_registry import NodesRegistryClient
from common import bls, utils
from common.db import zdb
from common.logger import zlogger
from common.errors import ErrorCodes
from config import zconfig

switch_lock: threading.Lock = threading.Lock()


def check_finalization() -> None:
    """Check and add not finalized batches to missed batches."""
    for app_name in list(zconfig.APPS.keys()):
        not_finalized_batches: dict[str, Any] = zdb.get_not_finalized_batches(app_name)
        if not_finalized_batches:
            zdb.add_missed_batches(app_name=app_name, batches_data=not_finalized_batches)


def send_batches() -> None:
    """Send batches for all apps."""
    for app_name in list(zconfig.APPS.keys()):
        while True:
            response = send_app_batches(app_name).get("data", {})
            sequencer_last_finalized_hash = response.get("finalized", {}).get("hash", "")
            if not sequencer_last_finalized_hash or \
                    zdb.get_batch(app_name, sequencer_last_finalized_hash):
                zconfig.IS_SYNCING = False
                break


def send_app_batches(app_name: str) -> dict[str, Any]:
    """Send batches for a specific app."""
    initialized_batches: dict[str, Any] = zdb.get_batches(
        app_name=app_name, states={"initialized"}
    )

    last_synced_batch: dict[str, Any] = zdb.get_last_batch(
        app_name=app_name, state="sequenced"
    )
    last_locked_batch: dict[str, Any] = zdb.get_last_batch(
        app_name=app_name, state="locked"
    )

    concat_hash: str = "".join(initialized_batches.keys())
    concat_sig: str = utils.eth_sign(concat_hash)
    data: str = json.dumps(
        {
            "app_name": app_name,
            "batches": list(initialized_batches.values()),
            "node_id": zconfig.NODE["id"],
            "signature": concat_sig,
            "sequenced_index": last_synced_batch.get("index", 0),
            "sequenced_hash": last_synced_batch.get("hash", ""),
            "sequenced_chaining_hash": last_synced_batch.get("chaining_hash", ""),
            "locked_index": last_locked_batch.get("index", 0),
            "locked_hash": last_locked_batch.get("hash", ""),
            "locked_chaining_hash": last_locked_batch.get("chaining_hash", ""),
            "timestamp": int(time.time()),
        }
    )

    url: str = f'{zconfig.SEQUENCER["socket"]}/sequencer/batches'
    response: dict[str, Any] = {}
    try:
        response = requests.put(
            url=url, data=data, headers=zconfig.HEADERS
        ).json()
        if response["status"] == "error":
            if response["error"]["code"] == ErrorCodes.INVALID_NODE_VERSION:
                zlogger.warning(response["error"]["message"])
                return {}
            zdb.add_missed_batches(app_name=app_name, batches_data=initialized_batches)
            return {}

        sequencer_resp = response["data"]
        censored_batches = sync_with_sequencer(
            app_name=app_name,
            initialized_batches=initialized_batches,
            sequencer_response=sequencer_resp,
        )
        zdb.is_sequencer_down = False
        if not censored_batches:
            zdb.empty_missed_batches(app_name)

            seq_tag = max(sequencer_resp["locked"]["tag"], sequencer_resp["finalized"]["tag"])
            if seq_tag != 0:
                zconfig.NETWORK_STATUS_TAG = seq_tag

    except Exception:
        zlogger.exception("An unexpected error occurred:")
        zdb.add_missed_batches(app_name=app_name, batches_data=initialized_batches)
        zdb.is_sequencer_down = True

    check_finalization()
    return response


def sync_with_sequencer(
        app_name: str, initialized_batches: dict[str, Any], sequencer_response: dict[str, Any]
) -> dict[str, Any]:
    """Sync batches with the sequencer."""
    zdb.upsert_sequenced_batches(app_name=app_name, batches_data=sequencer_response["batches"])
    last_locked_index: str = zdb.apps[app_name]["last_locked_batch"].get("index", 0)
    if sequencer_response["locked"]["index"] > last_locked_index:
        if is_sync_point_signature_verified(
                app_name=app_name,
                state="sequenced",
                index=sequencer_response["locked"]["index"],
                batch_hash=sequencer_response["locked"]["hash"],
                chaining_hash=sequencer_response["locked"]["chaining_hash"],
                tag=sequencer_response["locked"]["tag"],
                signature_hex=sequencer_response["locked"]["signature"],
                nonsigners=sequencer_response["locked"]["nonsigners"],
        ):
            zdb.update_locked_batches(
                app_name=app_name,
                sig_data=sequencer_response["locked"],
            )
        else:
            zlogger.error("Invalid locking signature received from sequencer")

    last_finalized_index: str = zdb.apps[app_name]["last_finalized_batch"].get("index", 0)
    if sequencer_response["finalized"]["index"] > last_finalized_index:
        if is_sync_point_signature_verified(
                app_name=app_name,
                state="locked",
                index=sequencer_response["finalized"]["index"],
                batch_hash=sequencer_response["finalized"]["hash"],
                chaining_hash=sequencer_response["finalized"]["chaining_hash"],
                tag=sequencer_response["finalized"]["tag"],
                signature_hex=sequencer_response["finalized"]["signature"],
                nonsigners=sequencer_response["finalized"]["nonsigners"],
        ):
            zdb.update_finalized_batches(
                app_name=app_name,
                sig_data=sequencer_response["finalized"],
            )
        else:
            zlogger.error("Invalid finalizing signature received from sequencer")

    return check_censorship(
        app_name=app_name,
        initialized_batches=initialized_batches,
        sequencer_response=sequencer_response,
    )


def check_censorship(
        app_name: str, initialized_batches: dict[str, Any], sequencer_response: dict[str, Any]
) -> dict[str, Any]:
    """Check for censorship and update missed batches."""
    sequenced_hashes: set[str] = set(batch["hash"] for batch in sequencer_response["batches"])
    censored_batches: dict[str, Any] = {
        batch_hash: batch
        for batch_hash, batch in initialized_batches.items()
        if batch_hash not in sequenced_hashes
    }

    # remove sequenced batches from the missed batches dict
    missed_batches: dict[str, Any] = {
        batch_hash: batch
        for batch_hash, batch in list(zdb.get_missed_batches(app_name).items())
        if batch_hash not in sequenced_hashes
    }

    # add censored batches to the missed batches dict
    missed_batches.update(censored_batches)

    zdb.set_missed_batches(app_name=app_name, batches_data=missed_batches)
    return censored_batches


def sign_sync_point(sync_point: dict[str, Any]) -> str:
    """confirm and sign the sync point"""
    batch: dict[str, Any] = zdb.get_batch(sync_point["app_name"], sync_point["hash"])
    for key in ["app_name", "state", "index", "hash", "chaining_hash"]:
        if batch.get(key) != sync_point[key]:
            return ""
    message: str = utils.gen_hash(json.dumps(sync_point, sort_keys=True))
    signature = bls.bls_sign(message)
    return signature


def _validate_nonsigners_stake(nonsigners_stake: int):
    """Verify the nonsigners' stake."""
    return 100 * nonsigners_stake / zconfig.TOTAL_STAKE <= 100 - zconfig.THRESHOLD_PERCENT


def compute_signature_public_key(nodes_info, agg_pub_key, non_signers: List[str]) -> attestation.G2Point:
    aggregated_public_key: attestation.G2Point = agg_pub_key
    for node_id in non_signers:
        aggregated_public_key -= nodes_info[node_id]["public_key_g2"]
    return aggregated_public_key


def is_sync_point_signature_verified(
        app_name: str,
        state: str,
        index: int,
        batch_hash: str,
        chaining_hash: str,
        tag: int,
        signature_hex: str,
        nonsigners: list[str],
) -> bool:
    '''
    Should first load the state of network nodes info using signature tag

    Verify the BLS signature of a synchronization point.
    '''
    network_state = zconfig.get_network_state(tag=tag)
    nodes_info = network_state.nodes

    nonsigners_stake = sum([nodes_info.get(node_id, {}).get("stake", 0) for node_id in nonsigners])
    agg_pub_key = compute_signature_public_key(nodes_info,
                                               network_state.aggregated_public_key,
                                               nonsigners)

    if not _validate_nonsigners_stake(nonsigners_stake):
        zlogger.exception("Signature with invalid stake from sequencer")
        return False

    data: str = json.dumps(
        {
            "app_name": app_name,
            "state": state,
            "index": index,
            "hash": batch_hash,
            "chaining_hash": chaining_hash,
        },
        sort_keys=True,
    )
    message: str = utils.gen_hash(data)
    zlogger.info(f"data: {data}, message: {message}, nonsigners: {nonsigners}")
    return bls.is_bls_sig_verified(signature_hex=signature_hex,
                                   message=message,
                                   public_key=agg_pub_key, )


async def gather_disputes(
        dispute_tasks: dict[asyncio.Task, str]
) -> dict[str, Any] | None:
    """Gather dispute data from nodes until the stake of nodes reaches the threshold"""
    results = []
    pending_tasks = list(dispute_tasks.keys())
    stake_percent = 100 * zconfig.NODES[zconfig.NODE['id']]['stake'] / zconfig.TOTAL_STAKE
    while pending_tasks and stake_percent < zconfig.THRESHOLD_PERCENT:
        done, pending_tasks = await asyncio.wait(pending_tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            if not task.result() or not utils.is_dispute_approved(task.result()):
                continue
            results.append(task.result())
            node_id = dispute_tasks[task]
            stake_percent += 100 * zconfig.NODES[node_id]['stake'] / zconfig.TOTAL_STAKE
    return results, stake_percent


async def send_dispute_requests() -> None:
    """Send dispute requests if there are missed batches."""
    if zconfig.IS_SYNCING or (not zdb.has_missed_batches() and not zdb.is_sequencer_down) \
            or zdb.pause_node.is_set():
        return

    timestamp: int = int(time.time())
    new_sequencer_id: str = utils.get_next_sequencer_id(
        old_sequencer_id=zconfig.SEQUENCER["id"]
    )
    proofs: list[dict[str, Any]] = []
    proofs.append(
        {
            "node_id": zconfig.NODE["id"],
            "old_sequencer_id": zconfig.SEQUENCER["id"],
            "new_sequencer_id": new_sequencer_id,
            "timestamp": timestamp,
            "signature": utils.eth_sign(f'{zconfig.SEQUENCER["id"]}{timestamp}'),
        }
    )
    apps_missed_batches: dict[str, Any] = {}

    for app_name in list(zconfig.APPS.keys()):
        app_missed_batches = zdb.get_missed_batches(app_name)
        if len(app_missed_batches) > 0:
            apps_missed_batches[app_name] = app_missed_batches

    dispute_tasks: dict[asyncio.Task, str] = {
        asyncio.create_task(
            send_dispute_request(node, apps_missed_batches, zdb.is_sequencer_down)
        ): node['id']
        for node in list(zconfig.NODES.values()) if node['id'] != zconfig.NODE['id']
    }
    try:
        responses, stake_percent = await asyncio.wait_for(gather_disputes(dispute_tasks),
                                                          timeout=zconfig.AGGREGATION_TIMEOUT)
    except asyncio.TimeoutError:
        zlogger.warning(f"Aggregation of signatures timed out after {zconfig.AGGREGATION_TIMEOUT} seconds.")
        return
    except Exception as error:
        zlogger.exception(f"An unexpected error occurred: {error}")
        return None

    if not responses or stake_percent < zconfig.THRESHOLD_PERCENT:
        return
    proofs.extend(responses)

    zdb.pause_node.set()
    old_sequencer_id, new_sequencer_id = utils.get_switch_parameter_from_proofs(
        proofs
    )
    switch_sequencer(old_sequencer_id, new_sequencer_id)
    send_switch_requests(proofs)


async def send_dispute_request(
        node: dict[str, Any], apps_missed_batches: dict[str, Any], is_sequencer_down: bool
) -> dict[str, Any] | None:
    """Send a dispute request to a specific node."""
    timestamp: int = int(time.time())
    data: str = json.dumps(
        {
            "sequencer_id": zconfig.SEQUENCER["id"],
            "apps_missed_batches": apps_missed_batches,
            "is_sequencer_down": is_sequencer_down,
            "timestamp": timestamp,
        }
    )
    url: str = f'{node["socket"]}/node/dispute'
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url=url, data=data, headers=zconfig.HEADERS) as response:
                response_json: dict[str, Any] = await response.json()
                if response_json["status"] == "success":
                    return response_json.get("data")
    except aiohttp.ClientError as error:
        zlogger.warning(f"Error sending dispute request to {node['id']}: {error}")


def send_switch_requests(proofs: list[dict[str, Any]]) -> None:
    """Send switch requests to all nodes except self."""
    zlogger.info("sending switch requests...")
    for node in list(zconfig.NODES.values()):
        if node["id"] == zconfig.NODE["id"]:
            continue

        data: str = json.dumps(
            {
                "proofs": proofs,
                "timestamp": int(time.time()),
            }
        )
        url: str = f'{node["socket"]}/node/switch'
        try:
            requests.post(url=url, data=data, headers=zconfig.HEADERS)
        except Exception as error:
            zlogger.exception(f"Error sending switch request to {node['id']}: {error}")


def switch_sequencer(old_sequencer_id: str, new_sequencer_id: str) -> bool:
    """Switch the sequencer if the proofs are approved."""
    with switch_lock:
        if old_sequencer_id != zconfig.SEQUENCER["id"]:
            zlogger.warning(
                f"Old sequencer ID mismatch: expected {zconfig.SEQUENCER['id']}, got {old_sequencer_id}"
            )
            zdb.pause_node.clear()
            return False

        zconfig.update_sequencer(new_sequencer_id)
        if new_sequencer_id != zconfig.SEQUENCER["id"]:
            zlogger.warning("Sequencer was not updated")
            zdb.pause_node.clear()
            return False

        for app_name in list(zconfig.APPS.keys()):
            all_nodes_last_finalized_batch: dict[str, Any] = (
                find_all_nodes_last_finalized_batch(app_name)
            )
            zdb.reinitialize_db(
                app_name, new_sequencer_id, all_nodes_last_finalized_batch
            )
        if zconfig.NODE['id'] != zconfig.SEQUENCER['id']:
            time.sleep(10)

        zdb.reset_timestamps(app_name)
        zdb.pause_node.clear()
        return True


def find_all_nodes_last_finalized_batch(app_name: str) -> dict[str, Any]:
    """Find the last finalized batch from all nodes."""
    last_finalized_batch: dict[str, Any] = zdb.get_last_batch(
        app_name=app_name, state="finalized"
    )

    for node in list(zconfig.NODES.values()):
        if node["id"] == zconfig.NODE["id"]:
            continue

        url: str = f'{node["socket"]}/node/{app_name}/batches/finalized/last'
        try:
            response: dict[str, Any] = requests.get(
                url=url, headers=zconfig.HEADERS
            ).json()
            if response["status"] == "error":
                continue
            batch: dict[str, Any] = response["data"]
            if batch.get("index", 0) > last_finalized_batch.get("index", 0):
                last_finalized_batch = batch
        except Exception:
            zlogger.exception("An unexpected error occurred:")

    return last_finalized_batch
