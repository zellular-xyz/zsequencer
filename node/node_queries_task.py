import asyncio
from typing import Any, Dict, List

import aiohttp

from common.batch import stateful_batch_to_batch_record
from common.db import zdb
from common.logger import zlogger
from config import zconfig


async def fetch_node_last_finalized_batch(session: aiohttp.ClientSession,
                                          node: Dict[str, Any],
                                          app_name: str) -> Dict[str, Any]:
    """Fetch last finalized batch from a single node asynchronously."""
    url = f'{node["socket"]}/node/{app_name}/batches/finalized/last'
    try:
        async with session.get(url, headers=zconfig.HEADERS, timeout=aiohttp.ClientTimeout(total=10)) as response:
            data = await response.json()
            if data.get("status") == "error":
                return {}
            return stateful_batch_to_batch_record(data["data"])
    except Exception as e:
        return {"error": f"Node {node['id']} failed: {str(e)}"}


async def fetch_all_nodes(app_name: str, nodes_to_query: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Fetch finalized batch records from all nodes asynchronously."""
    if not nodes_to_query:
        return []

    async with aiohttp.ClientSession() as session:
        tasks = [fetch_node_last_finalized_batch(session, node, app_name) for node in nodes_to_query]
        return await asyncio.gather(*tasks)


async def find_highest_finalized_batch_record_async(app_name: str) -> Dict[str, Any]:
    """Asynchronous version of find_highest_finalized_batch_record."""
    last_finalized_batch_record = zdb.get_last_operational_batch_record_or_empty(
        app_name=app_name, state="finalized"
    )

    nodes_to_query = [node for node in zconfig.NODES.values() if node["id"] != zconfig.NODE["id"]]

    if not nodes_to_query:
        return last_finalized_batch_record

    results = await fetch_all_nodes(app_name, nodes_to_query)

    # Log errors if any
    errors = [res["error"] for res in results if isinstance(res, dict) and "error" in res]
    if errors:
        zlogger.error("Errors occurred during node queries:\n" + "\n".join(errors))

    # Find highest finalized batch record
    for batch_record in results:
        if isinstance(batch_record, dict) and "index" in batch_record:
            if batch_record.get("index", 0) > last_finalized_batch_record.get("index", 0):
                last_finalized_batch_record = batch_record

    return last_finalized_batch_record


def find_highest_finalized_batch_record(app_name: str) -> Dict[str, Any]:
    """
    Find the last finalized batch record from all nodes.
    This function can be called from either synchronous or asynchronous contexts.
    """
    try:
        # Check if we're already in an event loop
        loop = asyncio.get_running_loop()
        # If we are, create a task and ensure it's properly awaited
        return asyncio.run_coroutine_threadsafe(
            find_highest_finalized_batch_record_async(app_name), loop
        ).result()
    except RuntimeError:
        # No running event loop, safe to use run_until_complete
        return asyncio.run(find_highest_finalized_batch_record_async(app_name))