"""This module implements sequencer switching and dispute resolution logic."""

from __future__ import annotations

import asyncio
import time
from asyncio import Lock
from typing import Any, TypedDict

from aiohttp.client_exceptions import ClientError
from aiohttp.web import HTTPError

from common import auth, bls, utils
from common.api_models import DisputeRequest, SwitchProof, SwitchRequest
from common.batch import BatchRecord, stateful_batch_to_batch_record
from common.batch_sequence import BatchSequence
from common.bls import is_sync_point_signature_verified
from common.db import zdb
from common.logger import zlogger
from common.sequencer_manager import zsequencer_manager
from config import zconfig


# Define types
class LastLockedBatchEntry(TypedDict):
    node_id: str
    last_locked_batch: BatchRecord


_switch_lock: Lock = Lock()


async def send_dispute_request(
    node: dict[str, Any],
    sequencer_id: str,
    timestamp: int,
) -> SwitchProof | None:
    """Send a dispute request to a specific node."""
    request = DisputeRequest(
        sequencer_id=sequencer_id,
        apps_censored_batches=zdb.get_apps_censored_batch_bodies(),
        timestamp=timestamp,
    )
    url = f"{node['socket']}/node/dispute"
    try:
        async with auth.create_session() as session:
            async with session.post(
                url=url,
                json=request.model_dump(),
            ) as response:
                response_json = await response.json()
                if response_json["status"] == "success" and "data" in response_json:
                    data = response_json["data"]
                    return SwitchProof(
                        node_id=node["id"],
                        sequencer_id=sequencer_id,
                        timestamp=timestamp,
                        signature=data["signature"],
                    )
    except (ClientError, HTTPError, asyncio.TimeoutError) as error:
        zlogger.warning(f"Error sending dispute request to {node['id']}: {error}")

    return None


async def gather_disputes(
    sequencer_id: str, timestamp: int
) -> tuple[list[SwitchProof], float]:
    """Gather dispute data from nodes until the stake of nodes reaches the threshold."""
    dispute_tasks: dict[asyncio.Task, str] = {
        asyncio.create_task(send_dispute_request(node, sequencer_id, timestamp)): node[
            "id"
        ]
        for node in list(zconfig.last_state.attesting_nodes.values())
        if node["id"] != zconfig.NODE["id"]
    }

    results: list[SwitchProof] = []
    pending_tasks = list(dispute_tasks.keys())
    stake_percent = (
        100 * zconfig.NODES[zconfig.NODE["id"]]["stake"] / zconfig.TOTAL_STAKE
    )
    while pending_tasks and stake_percent < zconfig.THRESHOLD_PERCENT:
        done, pending_tasks = await asyncio.wait(
            pending_tasks,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in done:
            if not task.result() or not is_dispute_approved(task.result()):
                continue
            results.append(task.result())
            node_id = dispute_tasks[task]
            stake_percent += 100 * zconfig.NODES[node_id]["stake"] / zconfig.TOTAL_STAKE
    return results, stake_percent


async def send_dispute_requests() -> None:
    """Send dispute requests if sequencer has a malfunction."""
    is_not_synced = not zconfig.get_synced_flag()
    is_paused = zconfig.is_paused

    no_censorship = not zdb.is_sequencer_censoring()
    no_delayed_batches = not zdb.has_delayed_batches()
    sequencer_up = not zdb.is_sequencer_down

    no_functionality_issue = no_censorship and no_delayed_batches and sequencer_up

    if is_not_synced or is_paused or no_functionality_issue:
        return

    zlogger.warning(
        f"Sending dispute {is_not_synced=}, {no_delayed_batches=}, {no_censorship=}, {sequencer_up=}, {is_paused=}"
    )
    timestamp = int(time.time())
    sequencer_id = zconfig.SEQUENCER["id"]
    # Create the initial SwitchProof from this node
    message = utils.gen_hash(f"{zconfig.SEQUENCER['id']}{timestamp}")
    proofs = [
        SwitchProof(
            node_id=zconfig.NODE["id"],
            sequencer_id=sequencer_id,
            timestamp=timestamp,
            signature=bls.bls_sign(message),
        )
    ]

    try:
        gathered_proofs, stake_percent = await asyncio.wait_for(
            gather_disputes(sequencer_id, timestamp),
            timeout=zconfig.AGGREGATION_TIMEOUT,
        )
    except asyncio.TimeoutError:
        zlogger.warning(
            f"Aggregation of signatures timed out after {zconfig.AGGREGATION_TIMEOUT} seconds.",
        )
        return

    except Exception as error:
        zlogger.error(f"An unexpected error occurred while gathering disputes: {error}")
        return

    if not gathered_proofs or stake_percent < zconfig.THRESHOLD_PERCENT:
        zlogger.warning(
            f"Not enough stake for dispute, stake_percent : {stake_percent}"
        )
        return
    proofs.extend(gathered_proofs)

    asyncio.create_task(send_switch_requests(proofs))
    new_sequencer_id = get_next_sequencer_id(sequencer_id)
    await switch_to_sequencer(new_sequencer_id)


async def _send_switch_request(session, node, proofs: list[SwitchProof]):
    """Send a single switch request to a node."""
    url = f"{node['socket']}/node/switch"

    try:
        async with session.post(
            url, json=SwitchRequest(proofs=proofs).model_dump()
        ) as response:
            await response.text()
    except (HTTPError, ClientError, asyncio.TimeoutError) as e:
        zlogger.warning(
            f"Error occurred while sending switch request to {node['id']}: {e}"
        )


async def send_switch_requests(proofs: list[SwitchProof]) -> None:
    """Send switch requests to all nodes except self asynchronously."""
    zlogger.warning("sending switch requests...")
    async with auth.create_session() as session:
        tasks = [
            _send_switch_request(session, node, proofs)
            for node in zconfig.NODES.values()
            if node["id"] != zconfig.NODE["id"]
        ]
        await asyncio.gather(*tasks)


async def switch_to_sequencer(new_sequencer_id: str) -> None:
    """
    Core implementation of sequencer switching process.
    """
    if new_sequencer_id == zconfig.SEQUENCER["id"]:
        zlogger.info(f"{new_sequencer_id} is already the sequencer.")
        return

    async with _switch_lock:
        try:
            zconfig.pause()
            zconfig.update_sequencer(new_sequencer_id)
            await _sync_with_latest_locks()

            for app_name in zconfig.APPS:
                zdb.apps[app_name]["nodes_state"] = {}
                zdb.reset_latency_queue(app_name)

            if zconfig.is_sequencer:
                zlogger.info(
                    f"This node is acting as the SEQUENCER. ID: {zconfig.NODE['id']}"
                )

                zsequencer_manager.has_received_nodes_put_batches = False
                for app_name in zconfig.APPS:
                    # Clear initialized batches if this node becomes the new sequencer.
                    # These batches can not be added to the operational pool as sequenced,
                    # because if their number exceeds the per-node quota, batches from other
                    # nodes might not be returned immediately.
                    # This could lead to disputes against the new leader because of censorship.
                    zdb.clear_initialized_batch_bodies(app_name=app_name)

            else:
                duration = zconfig.SEQUENCER_SETUP_DEADLINE_TIME_IN_SECONDS
                zlogger.info(
                    f"Waiting for {duration} seconds before start sending requests to the new sequencer."
                )
                await asyncio.sleep(duration)

        finally:
            zconfig.unpause()


async def _sync_with_latest_locks() -> None:
    """Sync the node with the latest network lock."""

    network_last_locked_batch_entries = (
        await get_network_last_locked_batch_entries_sorted()
    )

    for app_name, entries in network_last_locked_batch_entries.items():
        zdb.reinitialize_sequenced_batches(app_name=app_name)
        self_node_last_locked_record = zdb.get_last_operational_batch_record_or_empty(
            app_name=app_name, state="locked"
        )
        for entry in entries:
            node_id, last_locked_batch_record = (
                entry["node_id"],
                entry["last_locked_batch"],
            )
            last_locked_batch = last_locked_batch_record.get("batch")
            # does not need to process node-id with invalid last
            if "lock_signature" not in last_locked_batch:
                zlogger.warning(
                    f"Node id: {node_id} claiming locked signature on index : {last_locked_batch_record.get('index')} does not have lock signature."
                )
                continue

            # The peer node which claims it has max locked signature index, has equal index with the self itself
            # so it is not necessary anymore to start any syncing process with that peer node
            self_node_last_locked_batch_index = self_node_last_locked_record.get(
                "index", BatchSequence.BEFORE_GLOBAL_INDEX_OFFSET
            )
            if last_locked_batch_record["index"] <= self_node_last_locked_batch_index:
                zlogger.info(
                    f"Node last locked batch index is higher than or equal to others at the network with index: {self_node_last_locked_batch_index}"
                )
                break

            # fixme: this is added to track rarely happening bug and should be removed
            if not last_locked_batch.get("locked_nonsigners"):
                zlogger.warning(
                    f"nonsigners should not be empty {last_locked_batch_record=}"
                )

            # peer node must contain locked signature on claimed index and the signature must be verified
            if not is_sync_point_signature_verified(
                app_name=app_name,
                state="sequenced",
                index=last_locked_batch_record.get("index"),
                chaining_hash=last_locked_batch.get("chaining_hash"),
                tag=last_locked_batch.get("locked_tag"),
                signature_hex=last_locked_batch.get("lock_signature"),
                nonsigners=last_locked_batch.get("locked_nonsigners", []),
            ):
                zlogger.warning(
                    f"Node id: {node_id} claiming locked signature on index : {last_locked_batch_record.get('index')} is not verified."
                )
                continue

            # Otherwise there is gap between the last in-memory sequenced batch index and the claiming lock batch
            result = await _sync_with_peer_node(
                peer_node_id=node_id,
                app_name=app_name,
                self_node_last_locked_index=self_node_last_locked_batch_index,
                target_locked_index=last_locked_batch_record["index"],
            )
            if result:
                # if the syncing process with claiming peer node was successful ,
                # break the process and it does not require to check any other more claiming node
                break


async def _sync_with_peer_node(
    peer_node_id: str,
    app_name: str,
    self_node_last_locked_index: int,
    target_locked_index: int,
) -> bool:
    peer_node_socket = zconfig.NODES[peer_node_id]["socket"]
    after_index = self_node_last_locked_index

    zdb.reinitialize_sequenced_batches(app_name=app_name)

    while True:
        try:
            async with auth.create_session() as session:
                url = f"{peer_node_socket}/node/{app_name}/batches/sequenced"
                params = {"after": after_index}

                async with session.get(
                    url,
                    params=params,
                ) as response:
                    data = await response.json()
        except (ClientError, HTTPError, asyncio.TimeoutError) as e:
            zlogger.warning(
                f"Error occurred while fetching batches from {peer_node_socket}: {e}"
            )
            return False

        if data.get("status") != "success" or not data.get("data"):
            return False

        batch_bodies = data["data"]["batches"]
        if not batch_bodies:
            return False

        locked_signature_info = data["data"]["locked"]
        finalized_signature_info = data["data"]["finalized"]
        last_page = (
            after_index <= target_locked_index <= after_index + len(batch_bodies)
        )

        if last_page and not locked_signature_info:
            zlogger.warning(
                f"While syncing with peer node: {peer_node_id}, the last page which contains the claiming locked index does not contain any locked singature!"
            )
            return False

        zdb.insert_sequenced_batch_bodies(app_name=app_name, batch_bodies=batch_bodies)

        if locked_signature_info:
            locking_result = zdb.lock_batches(
                app_name=app_name,
                signature_data=locked_signature_info,
            )
            if not locking_result:
                zlogger.warning(
                    f"peer node id: {peer_node_id} contains invalid lock signature on index: {locked_signature_info.get('index')}"
                )
                return False
        if finalized_signature_info:
            finalizing_result = zdb.finalize_batches(
                app_name=app_name,
                signature_data=finalized_signature_info,
            )
            if not finalizing_result:
                zlogger.warning(
                    f"peer node id: {peer_node_id} contains invalid finalized signature on index: {finalized_signature_info.get('index')}"
                )
                return False

        zlogger.info(
            f"Fetched {len(batch_bodies)} new batches from peer node {peer_node_id} for app {app_name}, continuing from index {after_index}"
        )
        if last_page:
            return True

        after_index += len(batch_bodies)


async def _fetch_node_last_locked_batch_records_or_none(
    session: auth.create_session, node_id: str
) -> dict[str, BatchRecord] | None:
    """
    Fetch last locked batches for all apps from a single node asynchronously.
    Returns None if any error occurs during the fetch operation.
    """
    socket = zconfig.NODES[node_id]["socket"]
    url = f"{socket}/node/batches/locked/last"
    try:
        async with session.get(url) as response:
            data = await response.json()

    except (ClientError, HTTPError, asyncio.TimeoutError) as e:
        zlogger.warning(f"Failed to fetch last locked record from node {socket}: {e}")
        return None

    if data.get("status") == "error":
        zlogger.warning(
            f"Failed to fetch last locked record from node {socket}: {data}"
        )
        return None

    return {
        app_name: stateful_batch_to_batch_record(data["data"][app_name])
        for app_name in zconfig.APPS
        if app_name in data["data"]
    }


async def get_network_last_locked_batch_entries_sorted() -> dict[
    str, list[LastLockedBatchEntry]
]:
    """
    Retrieves all nodes' last locked batch records sorted by batch index in descending order.
    Filters out None responses from nodes and only processes valid responses.
    """
    apps = list(zconfig.APPS.keys())
    self_node_id = zconfig.NODE["id"]

    # Initialize result dictionary with empty lists for each app
    all_records: dict[str, list[LastLockedBatchEntry]] = {
        app_name: [] for app_name in apps
    }

    # Query all other nodes
    nodes_to_query = [node_id for node_id in zconfig.NODES if node_id != self_node_id]

    # Query all nodes concurrently
    async with auth.create_session() as session:
        tasks_with_node_ids = {
            node_id: _fetch_node_last_locked_batch_records_or_none(session, node_id)
            for node_id in nodes_to_query
        }
        results = await asyncio.gather(*tasks_with_node_ids.values())

    # Process results and add to records, filtering out None responses
    for node_id, node_records in zip(tasks_with_node_ids.keys(), results):
        if node_records is None:  # Skip None responses
            continue

        for app_name, batch_record in node_records.items():
            # Does not need to add record with batch for any more processing:
            if not batch_record.get("batch"):
                continue

            all_records[app_name].append(
                {"node_id": node_id, "last_locked_batch": batch_record}
            )

    # Sort records for each app by index in descending order
    for app_name in apps:
        all_records[app_name].sort(
            key=lambda entry: entry["last_locked_batch"].get("index"), reverse=True
        )

    return all_records


def is_switch_approved(proofs: list[SwitchProof]) -> bool:
    """Check if the switch to a new sequencer is approved."""
    if len(set((proof.timestamp, proof.sequencer_id) for proof in proofs)) > 1:
        zlogger.warning(f"proofs are not on the same sequencer and timestamp: {proofs}")
        return False
    if len(set(proof.node_id for proof in proofs)) < len(proofs):
        zlogger.warning(f"there are duplicate proofs in the list: {proofs}")
        return False

    node_ids = [proof.node_id for proof in proofs if is_dispute_approved(proof)]
    stake = sum([zconfig.NODES[node_id]["stake"] for node_id in node_ids])
    return 100 * stake / zconfig.TOTAL_STAKE >= zconfig.THRESHOLD_PERCENT


def is_dispute_approved(proof: SwitchProof) -> bool:
    """Check if a dispute is approved based on the provided proof."""
    now = time.time()
    if not (now - 10 <= proof.timestamp <= now):
        zlogger.warning(f"Invalid dispute time: {proof}")
        return False
    message = utils.gen_hash(f"{proof.sequencer_id}{proof.timestamp}")
    return bls.is_bls_sig_verified(
        signature_hex=proof.signature,
        message=message,
        public_key=zconfig.NODES[proof.node_id]["public_key_g2"],
    )


def get_next_sequencer_id(old_sequencer_id: str) -> str:
    """Get the ID of the next sequencer in a circular sorted list."""
    sorted_nodes = sorted(
        zconfig.last_state.sequencing_nodes.values(), key=lambda x: x["id"]
    )

    ids = [node["id"] for node in sorted_nodes]

    try:
        index = ids.index(old_sequencer_id)
        return ids[(index + 1) % len(ids)]  # Circular indexing
    except ValueError:
        return ids[0]  # Default to first if old_sequencer_id is not found
