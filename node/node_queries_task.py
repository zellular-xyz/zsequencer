import asyncio
from typing import Any, Dict
import aiohttp
from common.batch import stateful_batch_to_batch_record
from common.logger import zlogger
from config import zconfig
from common.db import zdb


async def fetch_node_last_finalized_batch(
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


async def find_highest_finalized_batch_record_async(app_name: str) -> Dict[str, Any]:
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
                fetch_node_last_finalized_batch(session, node, app_name)
                for node in nodes_to_query
            ]
            results = await asyncio.gather(*tasks)

            # Find highest index among valid results
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


def find_highest_finalized_batch_record(app_name: str) -> Dict[str, Any]:
    """
    Thread-safe wrapper to find the highest finalized batch record.
    Can be called from both sync and async contexts.
    """
    try:
        # Try to get the current event loop
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're in an async context (like send_dispute_requests)
            # We need to create a new loop in this case
            new_loop = asyncio.new_event_loop()
            try:
                return new_loop.run_until_complete(find_highest_finalized_batch_record_async(app_name))
            finally:
                new_loop.close()
        else:
            # We have a loop but it's not running
            return loop.run_until_complete(find_highest_finalized_batch_record_async(app_name))
    except RuntimeError:
        # No event loop exists (like in run_switch_sequencer thread)
        # Create a new loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(find_highest_finalized_batch_record_async(app_name))
        finally:
            loop.close()