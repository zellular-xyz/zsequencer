import asyncio
import json
import time
from typing import Any, TypedDict

import aiohttp

from common import utils
from common.batch import Batch, BatchRecord, stateful_batch_to_batch_record
from common.batch_sequence import BatchSequence
from common.db import zdb
from common.logger import zlogger
from config import zconfig
from common.bls import is_sync_point_signature_verified

switch_lock: asyncio.Lock = asyncio.Lock()


class LastLockedBatchEntry(TypedDict):
    node_id: str
    last_locked_batch: BatchRecord


async def _send_switch_request(session, node, proofs):
    """Send a single switch request to a node."""
    data = json.dumps(
        {
            "proofs": proofs,
            "timestamp": int(time.time()),
        }
    )
    url = f"{node['socket']}/node/switch"

    try:
        async with session.post(url, data=data, headers=zconfig.HEADERS) as response:
            await response.text()  # Consume the response
    except Exception as e:
        zlogger.warning(
            f"Error occurred while sending switch request to {node['id']}: {e}"
        )


async def send_switch_requests(proofs: list[dict[str, Any]]) -> None:
    """Send switch requests to all nodes except self asynchronously."""
    zlogger.warning("sending switch requests...")
    async with aiohttp.ClientSession() as session:
        tasks = [
            _send_switch_request(session, node, proofs)
            for node in zconfig.NODES.values()
            if node["id"] != zconfig.NODE["id"]
        ]
        await asyncio.gather(*tasks)


def switch_sequencer(old_sequencer_id: str, new_sequencer_id: str):
    """
    Synchronous wrapper for sequencer switching.
    """
    asyncio.run(_switch_sequencer_core(old_sequencer_id, new_sequencer_id))


async def switch_sequencer_async(old_sequencer_id: str, new_sequencer_id: str):
    """
    Asynchronous version of sequencer switching.
    """
    await _switch_sequencer_core(old_sequencer_id, new_sequencer_id)


async def _switch_sequencer_core(old_sequencer_id: str, new_sequencer_id: str):
    """
    Core implementation of sequencer switching logic.
    Used by both sync and async switch functions.
    """
    if old_sequencer_id != zconfig.SEQUENCER["id"]:
        old_sequencer_node = zconfig.NODES[old_sequencer_id]
        zlogger.warning(
            f"Sequencer switch rejected: old sequencer {old_sequencer_node['socket']} does not match current sequencer {zconfig.SEQUENCER['socket']}"
        )
        return

    async with switch_lock:
        zdb.pause_node.set()

        try:
            zconfig.update_sequencer(new_sequencer_id)
            network_last_locked_batch_entries = await get_network_last_locked_batch_entries_sorted()

            for (app_name, entries) in network_last_locked_batch_entries.items():
                self_node_last_locked_record = zdb.get_last_operational_batch_record_or_empty(
                    app_name=app_name,
                    state="locked"
                )
                for entry in entries:
                    node_id, last_locked_batch_record = entry['node_id'], entry['last_locked_batch']
                    last_locked_batch = last_locked_batch_record.get("batch")
                    # does not need to process node-id with invalid last
                    if 'lock_signature' not in last_locked_batch:
                        zlogger.warning(f"Node id: {node_id} claiming locked signature on index : {last_locked_batch_record.get('index')} does not have lock signature.")
                        continue

                    # The peer node which claims it has max locked signature index, has equal index with the self itself
                    # so it is not necessary anymore to start any syncing process with that peer node
                    self_node_last_locked_batch_index = self_node_last_locked_record.get('index',
                                                                                              BatchSequence.BEFORE_GLOBAL_INDEX_OFFSET)
                    if last_locked_batch_record['index'] <= self_node_last_locked_batch_index:
                        zlogger.info(f"Node last locked batch index is higher than or equal to others at the network with index: {self_node_last_locked_batch_index}")
                        break

                    # peer node must contain locked signature on claimed index and the signature must be verified
                    if not is_sync_point_signature_verified(app_name=app_name,
                                                            state="sequenced",
                                                            index=last_locked_batch_record.get("index"),
                                                            batch_hash=last_locked_batch.get("hash"),
                                                            chaining_hash=last_locked_batch.get("chaining_hash"),
                                                            tag=last_locked_batch.get("locked_tag"),
                                                            signature_hex=last_locked_batch.get("lock_signature"),
                                                            nonsigners=last_locked_batch.get("locked_nonsigners")
                                                            ):
                        zlogger.warning(
                            f"Node id: {node_id} claiming locked signature on index : {last_locked_batch_record.get('index')} is not verified.")
                        continue

                    # Otherwise there is gap between the last in-memory sequenced batch index and the claiming lock batch
                    result = await _sync_with_peer_node(peer_node_id=node_id,
                                                  app_name=app_name,
                                                  self_node_last_locked_index=self_node_last_locked_batch_index,
                                                  target_locked_index=last_locked_batch_record["index"])
                    if result:
                        # if the syncing process with claiming peer node was successful ,
                        # break the process and it does not require to check any other more claiming node
                        break


            if zconfig.NODE["id"] != zconfig.SEQUENCER["id"]:
                await asyncio.sleep(zconfig.SEQUENCER_SETUP_DEADLINE_TIME_IN_SECONDS)
            for app_name in zconfig.APPS:
                zdb.initialize_missing_batches(app_name)
                if zconfig.NODE["id"] == new_sequencer_id:
                    zlogger.info(
                        "This node is acting as the SEQUENCER. ID: %s",
                        zconfig.NODE["id"],
                    )
                    zdb.sequence_initialized_batches(app_name)
                zdb.apps[app_name]["nodes_state"] = {}
                zdb.reset_latency_queue(app_name)
        finally:
            zdb.pause_node.clear()


async def _sync_with_peer_node(peer_node_id: str,
                               app_name: str,
                               self_node_last_locked_index: int,
                               target_locked_index: int) -> bool:
    peer_node_socket = zconfig.NODES[peer_node_id]["socket"]
    after_index = self_node_last_locked_index

    zdb.reinitialize_batches(app_name=app_name)

    #  timeout value (in seconds)
    timeout = aiohttp.ClientTimeout(total=10)

    async with (aiohttp.ClientSession(timeout=timeout) as session):
        while True:
            try:
                url = f"{peer_node_socket}/node/{app_name}/batches/sequenced"
                params = {"after": after_index}

                async with session.get(url, params=params, headers=zconfig.HEADERS) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        zlogger.warning(
                            f"Failed to fetch batches from node {peer_node_socket}: {error_text}")
                        return False

                    data = await response.json()
                    if data.get("status") != "success" or not data.get("data"):
                        return False

                    batch_bodies = data["data"]["batches"]
                    if not batch_bodies:
                        return False
                    chaining_hash = data["data"]["first_chaining_hash"]
                    locked_signature_info = data["data"]["locked"]
                    finalized_signature_info = data["data"]["finalized"]
                    last_page = after_index <= target_locked_index <= after_index + len(batch_bodies)
                    zlogger.warning(f"{after_index}, {chaining_hash}")
                    
                    batches: list[Batch] = []
                    for idx, batch_body in enumerate(batch_bodies):
                        batch_hash = utils.gen_hash(batch_body)
                        if idx > 0:
                            chaining_hash = utils.gen_hash(chaining_hash + batch_hash)
                        if idx < 3:
                            zlogger.warning(f"{idx}, {after_index}, {batch_hash}, {batch_body}")
                        batches.append(dict(app_name=app_name,
                                            node_id=peer_node_id,
                                            body=batch_body,
                                            hash=batch_hash,
                                            chaining_hash=chaining_hash))

                    # put signatures on corresponding batches, they are already verified
                    if locked_signature_info:
                        locked_signature_idx = locked_signature_info.get("index") if after_index == 0 else \
                            locked_signature_info.get("index") - (after_index+1)
                        batches[locked_signature_idx] = {
                            **batches[locked_signature_idx],
                            "lock_signature": locked_signature_info.get("signature"),
                            "locked_nonsigners": locked_signature_info.get("nonsigners"),
                            "locked_tag": locked_signature_info.get("tag")
                        }

                    if finalized_signature_info:
                        finalized_signature_idx = finalized_signature_info.get("index") if after_index == 0 else \
                            finalized_signature_info.get("index") - (after_index + 1)
                        batches[finalized_signature_idx] = {
                            **batches[finalized_signature_idx],
                            "finalization_signature": finalized_signature_info.get("signature"),
                            "finalized_nonsigners": finalized_signature_info.get("nonsigners"),
                            "finalized_tag": finalized_signature_info.get("tag")
                        }

                    if last_page and not locked_signature_info:
                        zlogger.warning(
                            f"While syncing with peer node: {peer_node_id}, the last page which contains the claiming locked index does not contain any locked singature!"
                        )
                        return False

                    result = zdb.insert_sequenced_batches(app_name=app_name, batches=batches)
                    if not result:
                        zlogger.warning(
                            f"Error while upserting sequenced batches, app_name:{app_name}, peer_node_id:{peer_node_id}")
                        return False

                    if locked_signature_info:
                        locking_result = zdb.lock_batches(app_name=app_name,
                                                          signature_data=dict(index=locked_signature_info.get("index"),
                                                                              chaining_hash=locked_signature_info.get(
                                                                                  "chaining_hash"),
                                                                              hash=locked_signature_info.get("hash"),
                                                                              signature=locked_signature_info.get(
                                                                                  "signature"),
                                                                              nonsigners=locked_signature_info.get(
                                                                                  "nonsigners"),
                                                                              tag=locked_signature_info.get("tag")))
                        if not locking_result:
                            zlogger.warning(
                                f"peer node id: {peer_node_id} contains invalid lock signature on index: {locked_signature_info.get('index')}"
                            )
                            return False
                    if finalized_signature_info:
                        finalizing_result = zdb.finalize_batches(app_name=app_name,
                                                                 signature_data=dict(
                                                                     index=finalized_signature_info.get("index"),
                                                                     chaining_hash=finalized_signature_info.get(
                                                                         "chaining_hash"),
                                                                     hash=finalized_signature_info.get("hash"),
                                                                     signature=finalized_signature_info.get(
                                                                         "signature"),
                                                                     nonsigners=finalized_signature_info.get(
                                                                         "nonsigners"),
                                                                     tag=finalized_signature_info.get("tag")))
                        if not finalizing_result:
                            zlogger.warning(
                                f"peer node id: {peer_node_id} contains invalid finalized signature on index: {finalized_signature_info.get('index')}"
                            )
                            return False

                    zlogger.info(
                        f"Fetched {len(batches)} new batches from peer node {peer_node_id} for app {app_name}, continuing from index {after_index}")
                    if last_page:
                        return True

                    after_index += len(batches)
            except Exception as e:
                zlogger.warning(f"Error occurred while fetching batches from {peer_node_socket}: {e}")
                return False


async def _fetch_node_last_locked_batch_records_or_empty(
        session: aiohttp.ClientSession,
        node_id: str
) -> dict[str, BatchRecord] | None:
    """
    Fetch last locked batches for all apps from a single node asynchronously.
    Returns None if any error occurs during the fetch operation.
    """
    socket = zconfig.NODES[node_id]["socket"]
    url = f"{socket}/node/batches/locked/last"
    try:
        async with session.get(
                url, headers=zconfig.HEADERS, timeout=aiohttp.ClientTimeout(total=10)
        ) as response:
            if response.status != 200:
                error_text = await response.text()
                zlogger.warning(
                    f"Failed to fetch last locked record from node {socket}: {error_text}"
                )
                return None

            data = await response.json()
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
    except Exception as e:
        zlogger.warning(
            f"Failed to fetch last locked record from node {socket}: {e}"
        )
        return None


async def get_network_last_locked_batch_entries_sorted() -> dict[str, list[LastLockedBatchEntry]]:
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
    async with aiohttp.ClientSession() as session:
        tasks_with_node_ids = [
            (node_id, _fetch_node_last_locked_batch_records_or_empty(session, node_id))
            for node_id in nodes_to_query
        ]
        results = await asyncio.gather(*(task for _, task in tasks_with_node_ids))

    # Process results and add to records, filtering out None responses
    for node_id, node_records in zip([node_id for node_id, _ in tasks_with_node_ids], results):
        if node_records is None:  # Skip None responses
            continue

        for app_name, batch_record in node_records.items():
            # Does not need to add record with batch for any more processing:
            if not batch_record.get("batch"):
                continue

            all_records[app_name].append({
                "node_id": node_id,
                "last_locked_batch": batch_record
            })

    # Sort records for each app by index in descending order
    for app_name in apps:
        all_records[app_name].sort(
            key=lambda entry: entry["last_locked_batch"].get("index"),
            reverse=True
        )

    return all_records
