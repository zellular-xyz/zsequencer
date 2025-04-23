import asyncio
import json
import time
from typing import Any, TypedDict

import aiohttp

from common.batch import Batch, BatchRecord, stateful_batch_to_batch_record
from common.db import zdb
from common.logger import zlogger
from common import utils
from config import zconfig
from node.signature_verification import is_sync_point_signature_verified

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
                self_node_last_locked_batch = zdb.get_last_operational_batch_record_or_empty(
                    app_name=app_name,
                    state="locked"
                )
                for entry in entries:
                    # The peer node which claims it has max locked signature index, has equal index with the self itself
                    # so it is not necessary anymore to start any syncing process with that peer node
                    if entry['last_locked_batch']['index'] == self_node_last_locked_batch['index']:
                        break

                    node_id, last_locked_batch_record = entry['node_id'], entry['last_locked_batch']
                    last_locked_batch = last_locked_batch_record.get("batch")

                    # peer node must contain locked signature on claimed index and the signature must be verified
                    if not is_sync_point_signature_verified(app_name=app_name,
                                                            state="locked",
                                                            index=last_locked_batch_record.get("index"),
                                                            batch_hash=last_locked_batch.get("hash"),
                                                            chaining_hash=last_locked_batch.get("chaining_hash"),
                                                            tag=last_locked_batch.get("locked_tag"),
                                                            signature_hex=last_locked_batch.get("lock_signature"),
                                                            nonsigners=last_locked_batch.get("locked_nonsigners")
                                                            ):
                        continue

                    # check whether the last locked index is already in self node memory and only promote
                    if entry['last_locked_batch']['index'] <= zdb.get_last_operational_batch_record_or_empty(
                            "sequenced").get("index"):
                        zdb.apps[app_name]["operational_batch_sequence"].promote(entry['last_locked_batch']['index'],
                                                                                 "locked")
                        break

                    # Otherwise there is gap between the last in-memory sequenced batch index and the claiming lock batch
                    result = await _sync_with_peer_node(peer_node_id=node_id,
                                                        app_name=app_name,
                                                        after=self_node_last_locked_batch["index"],
                                                        until=last_locked_batch_record["index"])
                    if result:
                        # if the syncing process with claiming peer node was successful ,
                        # break the process and it does not require to check any other more claiming node
                        break
                zdb.reinitialize(app_name, new_sequencer_id, last_locked_batch_record)
                zdb.reset_latency_queue(app_name)

            if zconfig.NODE["id"] != zconfig.SEQUENCER["id"]:
                await asyncio.sleep(10)
        finally:
            zdb.pause_node.clear()


async def _sync_with_peer_node(peer_node_id: str, app_name: str, after: int, until: int) -> bool:
    """
    Sync with a peer node on the network and retrieve batches in chunk mode.

    Args:
        peer_node_id: The ID of the peer node to sync with.
        app_name: The name of the app.
        after: The batch index number to retrieve batches after.
        until: The target batch index to sync up to.

    Returns:
        True if synchronization was successful, False otherwise.
    """
    peer_node_socket = zconfig.NODES[peer_node_id]["socket"]
    after_index = after

    try:
        async with aiohttp.ClientSession() as session:
            while True:
                url = f"{peer_node_socket}/node/{app_name}/batches/sequenced"
                params = {"after": after_index}

                try:
                    async with session.get(url, params=params, headers=zconfig.HEADERS) as response:
                        if response.status != 200:
                            zlogger.warning(
                                f"Failed to fetch batches from node {peer_node_socket}: {await response.text()}")
                            return False

                        data = await response.json()
                        if data.get("status") != "success" or not data.get("data"):
                            return False

                        batch_bodies = data["data"]["batches"]
                        if not batch_bodies:
                            return False

                        # last_locked_signature_info = data["data"]["locked"]
                        chaining_hash = data["data"]["first_chaining_hash"]

                        # verify first chaining hash string
                        last_sequenced_batch_chaining_hash = zdb \
                            .get_last_operational_batch_record_or_empty(state="sequenced") \
                            .get("batch") \
                            .get("chaining_hash")
                        expected_chaining_hash = utils.gen_hash(last_sequenced_batch_chaining_hash + batch_bodies[0])
                        if expected_chaining_hash != chaining_hash:
                            zlogger.warning(
                                f"Invalid chaining hash: expected {expected_chaining_hash} got {chaining_hash}"
                            )
                            return False

                        # verify finalized signature info if exists on peer node response
                        finalized_signature_info = data["data"]["finalized"]
                        if finalized_signature_info and not is_sync_point_signature_verified(
                                app_name=app_name,
                                state="finalized",
                                index=finalized_signature_info.get("index"),
                                batch_hash=finalized_signature_info.get("hash"),
                                chaining_hash=finalized_signature_info.get("chaining_hash"),
                                tag=finalized_signature_info.get("tag"),
                                signature_hex=finalized_signature_info.get("signature"),
                                nonsigners=finalized_signature_info.get("nonsigners")):
                            zlogger.warning("Invalid finalized signature")
                            return False

                        contain_target_locked_batch = after_index <= until <= after_index + len(batch_bodies)
                        if contain_target_locked_batch:
                            locked_signature_info = data["data"]["locked"]
                            if not locked_signature_info:
                                zlogger.warning(
                                    f"expected to find locked signature on the last page containing target locked batch")
                                return False

                            if locked_signature_info["index"] < until:
                                zlogger.warning(
                                    f"expected to find locked signature index be greater than or equal to the target locked: {until}")
                                return False

                            if locked_signature_info["index"] > until and not is_sync_point_signature_verified(
                                    app_name=app_name,
                                    state="locked",
                                    index=locked_signature_info.get("index"),
                                    batch_hash=locked_signature_info.get("hash"),
                                    chaining_hash=locked_signature_info.get("chaining_hash"),
                                    tag=locked_signature_info.get("tag"),
                                    signature_hex=locked_signature_info.get("signature"),
                                    nonsigners=locked_signature_info.get("nonsigners")):
                                zlogger.warning(f"locked signature verification failed at the last page")
                                return False

                        batches: list[Batch] = []
                        for batch_body in batch_bodies:
                            batch_hash = utils.gen_hash(batch_body)
                            chaining_hash = utils.gen_hash(chaining_hash + batch_hash)
                            batches.append(dict(app_name=app_name,
                                                node_id=peer_node_id,
                                                body=batch_body,
                                                hash=batch_hash,
                                                chaining_hash=chaining_hash))

                            # append signatures on corresponding batches, they are already verified
                            if locked_signature_info:
                                idx = locked_signature_info.get("index") - after_index
                                batches[idx]["lock_signature"] = locked_signature_info.get("signature")
                                batches[idx]["locked_nonsigners"] = locked_signature_info.get("nonsigners")
                                batches[idx]["locked_tag"] = locked_signature_info.get("tag")

                            if finalized_signature_info:
                                idx = finalized_signature_info.get("index") - after_index
                                batches[idx]["finalization_signature"] = finalized_signature_info.get("signature")
                                batches[idx]["finalized_nonsigners"] = finalized_signature_info.get("nonsigners")
                                batches[idx]["finalized_tag"] = finalized_signature_info.get("tag")

                        zdb.upsert_sequenced_batches(app_name=app_name, batches=batches)
                        if locked_signature_info:
                            zdb.upsert_locked_sync_point(app_name=app_name, sync_point=locked_signature_info)
                        if finalized_signature_info:
                            zdb.upsert_finalized_sync_point(app_name=app_name, sync_point=finalized_signature_info)

                        after_index += len(batches)
                        if contain_target_locked_batch:
                            break

                except Exception as e:
                    zlogger.warning(f"Error occurred while fetching batches from {peer_node_socket}: {e}")
                    return False

        return True

    except Exception as e:
        zlogger.warning(f"Failed to establish connection with peer node {peer_node_socket}: {e}")
        return False


async def get_network_last_locked_batch_entries() -> dict[str, LastLockedBatchEntry]:
    """Retrieves the last locked batch records from all network nodes."""
    apps = list(zconfig.APPS.keys())

    # Get local records first
    self_node_id = zconfig.NODE["id"]
    highest_records = {
        app_name: {"node_id": self_node_id,
                   "batch_record": zdb.get_last_operational_batch_record_or_empty(app_name=app_name, state="locked")}
        for app_name in apps
    }

    highest_indices = {
        app_name: entry["batch_record"].get("index", 0) for app_name, entry in highest_records.items()
    }

    # Filter nodes to exclude self
    nodes_to_query = [
        node for node in zconfig.NODES.values() if node["id"] != self_node_id
    ]

    if not nodes_to_query:
        return highest_records

    # Query all nodes concurrently
    async with aiohttp.ClientSession() as session:
        tasks_with_node_ids = [
            (node["id"], _fetch_node_last_locked_batch_records_or_empty(session, node))
            for node in nodes_to_query
        ]
        results = await asyncio.gather(*(task for _, task in tasks_with_node_ids))

    # Process results and find highest locked index for each app
    for node_id, node_records in zip([node_id for node_id, _ in tasks_with_node_ids], results):
        if not node_records:
            continue
        for app_name, record in node_records.items():
            record_index = record.get("index", 0)
            if record_index > highest_indices[app_name]:
                highest_indices[app_name] = record_index
                highest_records[app_name] = {"node_id": node_id, "batch_record": record}

    return highest_records


async def get_network_last_locked_batch_entries_sorted() -> dict[str, list[LastLockedBatchEntry]]:
    """Retrieves all nodes' last locked batch records sorted by batch index in descending order.
    If multiple nodes have the same highest index, prioritizes self node."""
    apps = list(zconfig.APPS.keys())
    self_node_id = zconfig.NODE["id"]

    # Initialize result dictionary with empty lists for each app
    all_records: dict[str, list[LastLockedBatchEntry]] = {
        app_name: [] for app_name in apps
    }

    # Add self node records
    for app_name in apps:
        last_locked_batch = zdb.get_last_operational_batch_record_or_empty(app_name=app_name, state="locked")
        all_records[app_name].append({
            "node_id": self_node_id,
            "last_locked_batch": last_locked_batch
        })

    # Query all other nodes
    nodes_to_query = [node_id for node_id in zconfig.NODES if node_id != self_node_id]

    # Query all nodes concurrently
    async with aiohttp.ClientSession() as session:
        tasks_with_node_ids = [
            (node_id, _fetch_node_last_locked_batch_records_or_empty(session, node_id))
            for node_id in nodes_to_query
        ]
        results = await asyncio.gather(*(task for _, task in tasks_with_node_ids))

    # Process results and add to records
    for node_id, node_records in zip([node_id for node_id, _ in tasks_with_node_ids], results):
        if not node_records:
            continue
        for app_name, batch_record in node_records.items():
            all_records[app_name].append({
                "node_id": node_id,
                "last_locked_batch": batch_record
            })

    for app_name in apps:
        all_records[app_name].sort(
            key=lambda entry: entry["last_locked_batch"]["index"],
            reverse=True
        )

    return all_records


async def _fetch_node_last_locked_batch_records_or_empty(
        session: aiohttp.ClientSession, node_id: str
) -> dict[str, BatchRecord]:
    """Fetch last locked batches for all apps from a single node asynchronously."""
    socket = zconfig.NODES[node_id]['socket']
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
                return {}

            data = await response.json()
            if data.get("status") == "error":
                zlogger.warning(
                    f"Failed to fetch last locked record from node {socket}: {data}"
                )
                return {}

            return {
                app_name: stateful_batch_to_batch_record(data["data"][app_name])
                for app_name in zconfig.APPS
                if app_name in data["data"]
            }
    except Exception as e:
        zlogger.warning(
            f"Failed to fetch last locked record from node {socket}: {e}"
        )
        return {}
