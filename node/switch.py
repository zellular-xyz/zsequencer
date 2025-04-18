import asyncio
import json
import time
from typing import Any

import aiohttp

from common.batch import BatchRecord
from common.batch import stateful_batch_to_batch_record
from common.db import zdb
from common.logger import zlogger
from config import zconfig

switch_lock: asyncio.Lock = asyncio.Lock()


async def _send_switch_request(session, node, proofs):
    """Send a single switch request to a node."""
    data = json.dumps({
        "proofs": proofs,
        "timestamp": int(time.time()),
    })
    url = f'{node["socket"]}/node/switch'

    try:
        async with session.post(url, data=data, headers=zconfig.HEADERS) as response:
            await response.text()  # Consume the response
    except Exception as e:
        zlogger.warning(f"Error occurred while sending switch request to {node['id']}: {e}")


async def send_switch_requests(proofs: list[dict[str, Any]]) -> None:
    """Send switch requests to all nodes except self asynchronously."""
    zlogger.warning("sending switch requests...")
    async with aiohttp.ClientSession() as session:
        tasks = [
            _send_switch_request(session, node, proofs)
            for node in zconfig.NODES.values() if node["id"] != zconfig.NODE["id"]
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
        zlogger.warning(f"Sequencer switch rejected: old sequencer {old_sequencer_node['socket']} does not match current sequencer {zconfig.SEQUENCER['socket']}")
        return

    async with switch_lock:
        zdb.pause_node.set()

        try:
            zconfig.update_sequencer(new_sequencer_id)

            all_nodes_last_finalized_batch_records = await get_network_last_finalized_batch_records()

            for app_name, batch_record in all_nodes_last_finalized_batch_records.items():
                if batch_record:
                    zdb.reinitialize(app_name, new_sequencer_id, batch_record)
                zdb.reset_not_finalized_batches_timestamps(app_name)

            if zconfig.NODE['id'] != zconfig.SEQUENCER['id']:
                await asyncio.sleep(10)
        finally:
            zdb.pause_node.clear()


async def _fetch_node_last_finalized_batch_records_or_empty(
        session: aiohttp.ClientSession,
        node: dict[str, Any]
) -> dict[str, BatchRecord]:
    """Fetch last finalized batches for all apps from a single node asynchronously."""
    url = f'{node["socket"]}/node/batches/finalized/last'
    try:
        async with session.get(
                url,
                headers=zconfig.HEADERS,
                timeout=aiohttp.ClientTimeout(total=10)
        ) as response:
            if response.status != 200:
                error_text = await response.text()
                zlogger.warning(f"Failed to fetch last finalized record from node {node['socket']}: {error_text}")
                return {}

            data = await response.json()
            if data.get("status") == "error":
                zlogger.warning(f"Failed to fetch last finalized record from node {node['socket']}: {data}")
                return {}

            return {
                app_name: stateful_batch_to_batch_record(data["data"][app_name])
                for app_name in zconfig.APPS
                if app_name in data["data"]
            }
    except Exception as e:
        zlogger.warning(f"Failed to fetch last finalized record from node {node['socket']}: {e}")
        return {}


async def get_network_last_finalized_batch_records() -> dict[str, BatchRecord]:
    """Retrieves the last finalized batch records from all network nodes."""
    apps = list(zconfig.APPS.keys())

    # Get local records first
    highest_records = {
        app_name: zdb.get_last_operational_batch_record_or_empty(
            app_name=app_name,
            state="finalized"
        )
        for app_name in apps
    }

    highest_indices = {
        app_name: record.get("index", 0)
        for app_name, record in highest_records.items()
    }

    # Filter nodes to exclude self
    nodes_to_query = [
        node for node in zconfig.NODES.values()
        if node["id"] != zconfig.NODE["id"]
    ]

    if not nodes_to_query:
        return highest_records

    # Query all nodes concurrently
    async with aiohttp.ClientSession() as session:
        tasks = [
            _fetch_node_last_finalized_batch_records_or_empty(session, node)
            for node in nodes_to_query
        ]
        results = await asyncio.gather(*tasks)

    # Process results and find last finalized index for each app
    for node_records in results:
        if not node_records:  # Skip empty or error results
            continue
        for app_name, record in node_records.items():
            record_index = record.get("index", 0)
            if record_index > highest_indices[app_name]:
                highest_indices[app_name] = record_index
                highest_records[app_name] = record

    return highest_records
