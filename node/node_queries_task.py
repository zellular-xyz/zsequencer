import asyncio
from typing import Any, Dict

import aiohttp
import nest_asyncio

from common.batch import stateful_batch_to_batch_record
from common.db import zdb
from common.logger import zlogger
from config import zconfig

# Apply nest_asyncio to allow nested event loops
nest_asyncio.apply()


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
        zlogger.error(
            f"Failed to query node {node['id']} for last finalized batch "
            f"at {url}: {str(e)}"
        )
        return {}


def find_highest_finalized_batch_record(app_name: str) -> Dict[str, Any]:
    """Find the last finalized batch record from all nodes synchronously using asyncio."""
    # Get local record first
    last_finalized_batch_record = zdb.get_last_operational_batch_record_or_empty(
        app_name=app_name, state="finalized"
    )

    # Filter nodes to exclude self
    nodes_to_query = [node for node in zconfig.NODES.values() if node["id"] != zconfig.NODE["id"]]

    # Define async helper function
    async def fetch_all_nodes():
        async with aiohttp.ClientSession() as session:
            tasks = [
                fetch_node_last_finalized_batch(session, node, app_name)
                for node in nodes_to_query
            ]
            return await asyncio.gather(*tasks, return_exceptions=True)

    # Use nest_asyncio to allow running this in an existing event loop
    results = asyncio.run(fetch_all_nodes())

    # Process results
    for batch_record in results:
        if isinstance(batch_record, dict):  # Check if result is not an exception
            if batch_record.get("index", 0) > last_finalized_batch_record.get("index", 0):
                last_finalized_batch_record = batch_record

    return last_finalized_batch_record
