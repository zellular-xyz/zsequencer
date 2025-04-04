import asyncio
from typing import Any

import aiohttp

from common.batch import stateful_batch_to_batch_record
from common.db import zdb
from common.batch import BatchRecord
from common.logger import zlogger
from config import zconfig


async def fetch_node_last_finalized_batch_record_or_empty(
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


async def _find_all_nodes_last_finalized_batch_record_core(app_name: str) -> dict[str, Any]:
    """Core async implementation to find all nodes last finalized batch record."""
    try:
        # Get local record first
        record = zdb.get_last_operational_batch_record_or_empty(
            app_name=app_name,
            state="finalized"
        )
        index = record.get("index", 0)

        # Filter nodes to exclude self
        nodes_to_query = [
            node for node in zconfig.NODES.values()
            if node["id"] != zconfig.NODE["id"]
        ]

        if not nodes_to_query:
            return record

        # Query all nodes concurrently
        async with aiohttp.ClientSession() as session:
            tasks = [
                fetch_node_last_finalized_batch_record_or_empty(session, node, app_name)
                for node in nodes_to_query
            ]
            results = await asyncio.gather(*tasks)

            # Process results and find last finalized index
            for record in results:
                if not record:  # Skip empty or error results
                    continue
                record_index = record.get("index", 0)
                if record_index > index:
                    index = record_index
                    record = record

        return record

    except Exception as e:
        zlogger.error(f"Error in find_all_nodes_last_finalized_batch_record: {str(e)}")
        # Return local record as fallback
        return zdb.get_last_operational_batch_record_or_empty(
            app_name=app_name,
            state="finalized"
        )


def find_all_nodes_last_finalized_batch_record(app_name: str) -> dict[str, Any]:
    """
    Synchronous wrapper to find the last finalized batch record.
    For async contexts, use find_all_nodes_last_finalized_batch_record_async instead.
    """
    try:
        return asyncio.run(_find_all_nodes_last_finalized_batch_record_core(app_name))
    except Exception as e:
        zlogger.error(f"Critical error in find_all_nodes_last_finalized_batch_record: {str(e)}")
        # Return local record as ultimate fallback
        return zdb.get_last_operational_batch_record_or_empty(
            app_name=app_name,
            state="finalized"
        )


async def find_all_nodes_last_finalized_batch_record_async(app_name: str) -> dict[str, Any]:
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
