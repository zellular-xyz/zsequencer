import asyncio
import json
import threading
import time
from typing import Any

import aiohttp

from common.batch import BatchRecord
from common.batch import stateful_batch_to_batch_record
from common.db import zdb
from common.logger import zlogger
from config import zconfig

switch_lock: threading.Lock = threading.Lock()


async def find_all_nodes_last_finalized_batch_record_async(app_name: str) -> BatchRecord:
    """
    Async wrapper to find the last finalized batch record of network.
    Can be called from async contexts.
    """
    try:
        # Get the result asynchronously
        return await _find_all_nodes_last_finalized_batch_record_core(app_name)
    except Exception as e:
        zlogger.error(f"Critical error in find_all_nodes_last_finalized_batch_record: {str(e)}")
        # Return local record as ultimate fallback
        return zdb.get_last_operational_batch_record_or_empty(
            app_name=app_name,
            state="finalized"
        )


async def _fetch_node_last_finalized_batch_record_or_empty(
        session: aiohttp.ClientSession,
        node: dict[str, Any],
        app_name: str
) -> BatchRecord:
    """Fetch last finalized batch from a single node asynchronously."""
    url = f'{node["socket"]}/node/{app_name}/batches/finalized/last'
    try:
        async with session.get(
                url,
                headers=zconfig.HEADERS,
                timeout=aiohttp.ClientTimeout(total=10)
        ) as response:
            if response.status != 200:
                return {}

            data = await response.json()
            if data.get("status") == "error":
                return {}

            return stateful_batch_to_batch_record(data["data"])
    except Exception as e:
        zlogger.warning(f"Failed to fetch from node {node['id']}: {str(e)}")
        return {}


async def _find_all_nodes_last_finalized_batch_record_core(app_name: str) -> BatchRecord:
    """Core async implementation to find all nodes last finalized batch record."""
    # Get local record first
    local_record = zdb.get_last_operational_batch_record_or_empty(
        app_name=app_name,
        state="finalized"
    )
    highest_record = local_record
    highest_index = local_record.get("index", 0)

    # Filter nodes to exclude self
    nodes_to_query = [
        node for node in zconfig.NODES.values()
        if node["id"] != zconfig.NODE["id"]
    ]

    if not nodes_to_query:
        return highest_record

        # Query all nodes concurrently
    async with aiohttp.ClientSession() as session:
        tasks = [
            _fetch_node_last_finalized_batch_record_or_empty(session, node, app_name)
            for node in nodes_to_query
        ]
        results = await asyncio.gather(*tasks)

        # Process results and find last finalized index
        for record in results:
            if not record:  # Skip empty or error results
                continue
            record_index = record.get("index", 0)
            if record_index > highest_index:
                highest_index = record_index
                highest_record = record

    return highest_record


async def send_switch_request(session, node, proofs):
    """Send a single switch request to a node."""
    data = json.dumps({
        "proofs": proofs,
        "timestamp": int(time.time()),
    })
    url = f'{node["socket"]}/node/switch'

    try:
        async with session.post(url, data=data, headers=zconfig.HEADERS) as response:
            await response.text()  # Consume the response
    except Exception as error:
        zlogger.error(f"Error occurred while sending switch request to {node['id']}")


async def send_switch_requests(proofs: list[dict[str, Any]]) -> None:
    """Send switch requests to all nodes except self asynchronously."""
    zlogger.warning("sending switch requests...")
    async with aiohttp.ClientSession() as session:
        tasks = [
            send_switch_request(session, node, proofs)
            for node in zconfig.NODES.values() if node["id"] != zconfig.NODE["id"]
        ]
        await asyncio.gather(*tasks)


def verify_switch_sequencer(old_sequencer_id: str) -> bool:
    return old_sequencer_id == zconfig.SEQUENCER["id"]


def switch_sequencer(old_sequencer_id: str, new_sequencer_id: str):
    """
    Synchronous wrapper for sequencer switching.
    """
    with switch_lock:
        asyncio.run(_switch_sequencer_core(old_sequencer_id, new_sequencer_id))


async def switch_sequencer_async(old_sequencer_id: str, new_sequencer_id: str):
    """
    Asynchronous version of sequencer switching.
    """
    with switch_lock:
        await _switch_sequencer_core(old_sequencer_id, new_sequencer_id)


async def _switch_sequencer_core(old_sequencer_id: str, new_sequencer_id: str):
    """
    Core implementation of sequencer switching logic.
    Used by both sync and async switch functions.
    """
    if not verify_switch_sequencer(old_sequencer_id):
        return

    zdb.pause_node.set()

    try:
        zconfig.update_sequencer(new_sequencer_id)

        tasks = [
            sync_app_finalized_state(app_name, new_sequencer_id)
            for app_name in list(zconfig.APPS.keys())
        ]
        await asyncio.gather(*tasks)

        if zconfig.NODE['id'] != zconfig.SEQUENCER['id']:
            await asyncio.sleep(10)
    finally:
        zdb.pause_node.clear()


async def sync_app_finalized_state(app_name: str, new_sequencer_id: str):
    """
    Process a single app during sequencer switch by updating its finalized batch records
    and resetting batch timestamps.

    Args:
        app_name: Name of the app to process
        new_sequencer_id: ID of the new sequencer
    """
    all_nodes_last_finalized_batch_record = await find_all_nodes_last_finalized_batch_record_async(app_name)
    if all_nodes_last_finalized_batch_record:
        zdb.reinitialize(app_name, new_sequencer_id, all_nodes_last_finalized_batch_record)
    zdb.reset_not_finalized_batches_timestamps(app_name)
