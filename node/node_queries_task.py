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


async def fetch_all_nodes(nodes: List[Dict[str, Any]], app_name: str) -> List[Dict[str, Any]]:
    """Fetch last finalized batches from all nodes asynchronously."""
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_node_last_finalized_batch(session, node, app_name) for node in nodes]
        return await asyncio.gather(*tasks)


def find_highest_finalized_batch_record(app_name: str) -> Dict[str, Any]:
    """Find the last finalized batch record from all nodes asynchronously."""
    last_finalized_batch_record = zdb.get_last_operational_batch_record_or_empty(
        app_name=app_name, state="finalized"
    )

    nodes_to_query = [node for node in zconfig.NODES.values() if node["id"] != zconfig.NODE["id"]]

    if not nodes_to_query:
        return last_finalized_batch_record

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop:
        results = loop.run_until_complete(fetch_all_nodes(nodes_to_query, app_name))
    else:
        results = asyncio.run(fetch_all_nodes(nodes_to_query, app_name))

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
