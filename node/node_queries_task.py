import asyncio
from typing import Any, Dict

import aiohttp

from common.batch import stateful_batch_to_batch_record
from common.db import zdb
from common.logger import zlogger
from config import zconfig


async def fetch_node_batch(
        session: aiohttp.ClientSession,
        node: Dict[str, Any],
        app_name: str,
        retries: int = 3
) -> Dict[str, Any]:
    """Fetch last finalized batch from a single node with retry logic."""
    if node["id"] == zconfig.NODE["id"]:
        return {}

    url = f'{node["socket"]}/node/{app_name}/batches/finalized/last'

    async def attempt_request():
        try:
            async with session.get(url, headers=zconfig.HEADERS) as response:
                data = await response.json()
                if data.get("status") == "error":
                    return {}
                return stateful_batch_to_batch_record(data["data"])
        except Exception as e:
            raise e

    for attempt in range(retries):
        try:
            return await attempt_request()
        except Exception as e:
            if attempt == retries - 1:
                zlogger.error(
                    f"Failed to query node {node['id']} for last finalized batch "
                    f"at {url} after {retries} attempts: {str(e)}"
                )
                return {}
            await asyncio.sleep(1)  # Delay before retry


async def async_find_highest_finalized_batch_record(app_name: str) -> Dict[str, Any]:
    """Find the last finalized batch record from all nodes concurrently."""
    # Get local record first
    last_finalized_batch_record = zdb.get_last_operational_batch_record_or_empty(
        app_name=app_name, state="finalized"
    )

    # Set up client session with timeout
    timeout = aiohttp.ClientTimeout(total=10)  # 10 second total timeout

    async with aiohttp.ClientSession(timeout=timeout) as session:
        tasks = [
            fetch_node_batch(session, node, app_name)
            for node in zconfig.NODES.values()
        ]

        # Wait for all responses concurrently
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        # Find the highest indexed batch record
        for batch_record in responses:
            if not isinstance(batch_record, dict):  # Skip exceptions
                continue
            if batch_record.get("index", 0) > last_finalized_batch_record.get("index", 0):
                last_finalized_batch_record = batch_record

    return last_finalized_batch_record


def find_highest_finalized_batch_record(app_name: str) -> Dict[str, Any]:
    """Synchronous wrapper for the async function."""
    return asyncio.run(async_find_highest_finalized_batch_record(app_name))
