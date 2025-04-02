import asyncio
from typing import Any, Dict
import aiohttp
from common.batch import stateful_batch_to_batch_record
from common.logger import zlogger
from config import zconfig
from common.db import zdb


async def fetch_node_last_finalized_batch_record_or_empty(
        session: aiohttp.ClientSession,
        node: Dict[str, Any],
        app_name: str
) -> Dict[str, Any]:
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


async def _find_all_nodes_last_finalized_batch_record_core(app_name: str) -> Dict[str, Any]:
    """Core async implementation to find highest finalized batch record."""
    try:
        # Get local record first
        highest_record = zdb.get_last_operational_batch_record_or_empty(
            app_name=app_name,
            state="finalized"
        )
        highest_index = highest_record.get("index", 0)

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
                fetch_node_last_finalized_batch_record_or_empty(session, node, app_name)
                for node in nodes_to_query
            ]
            results = await asyncio.gather(*tasks)

            # Process results and find highest index
            for record in results:
                if not record:  # Skip empty or error results
                    continue
                record_index = record.get("index", 0)
                if record_index > highest_index:
                    highest_index = record_index
                    highest_record = record

        return highest_record

    except Exception as e:
        zlogger.error(f"Error in find_highest_finalized_batch_record: {str(e)}")
        # Return local record as fallback
        return zdb.get_last_operational_batch_record_or_empty(
            app_name=app_name,
            state="finalized"
        )


def find_all_nodes_last_finalized_batch_record(app_name: str) -> Dict[str, Any]:
    """
    Thread-safe wrapper to find the highest finalized batch record.
    Can be called from both sync and async contexts.
    """
    try:
        # Check if we're in an async context
        try:
            loop = asyncio.get_event_loop()
            # We're in an async context, use await directly
            if loop.is_running():
                raise RuntimeError("Cannot run the event loop while another loop is running")
            return loop.run_until_complete(_find_all_nodes_last_finalized_batch_record_core(app_name))
        except RuntimeError:
            # We're in a sync context, create a new loop
            return asyncio.run(_find_all_nodes_last_finalized_batch_record_core(app_name))
    except Exception as e:
        zlogger.error(f"Critical error in find_highest_finalized_batch_record: {str(e)}")
        # Return local record as ultimate fallback
        return zdb.get_last_operational_batch_record_or_empty(
            app_name=app_name,
            state="finalized"
        )


async def find_all_nodes_last_finalized_batch_record_async(app_name: str) -> Dict[str, Any]:
    """
    Async wrapper to find the highest finalized batch record.
    Can be called from async contexts.
    """
    try:
        # Get the result asynchronously
        return await _find_all_nodes_last_finalized_batch_record_core(app_name)
    except Exception as e:
        zlogger.error(f"Critical error in find_highest_finalized_batch_record: {str(e)}")
        # Return local record as ultimate fallback
        return zdb.get_last_operational_batch_record_or_empty(
            app_name=app_name,
            state="finalized"
        )