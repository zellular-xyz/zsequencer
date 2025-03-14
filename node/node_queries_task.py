from typing import Any, Dict
from concurrent.futures import ThreadPoolExecutor
import requests

from common.batch import stateful_batch_to_batch_record
from common.db import zdb
from common.logger import zlogger
from config import zconfig


def fetch_node_last_finalized_batch(node: Dict[str, Any], app_name: str) -> Dict[str, Any]:
    """Fetch last finalized batch from a single node."""
    url = f'{node["socket"]}/node/{app_name}/batches/finalized/last'
    try:
        response = requests.get(url, headers=zconfig.HEADERS, timeout=10)  # 10-second timeout per request
        data = response.json()
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
    """Find the last finalized batch record from all nodes using threads."""
    # Get local record first
    last_finalized_batch_record = zdb.get_last_operational_batch_record_or_empty(
        app_name=app_name, state="finalized"
    )

    # Filter nodes to exclude self
    nodes_to_query = [node for node in zconfig.NODES.values() if node["id"] != zconfig.NODE["id"]]

    # Use ThreadPoolExecutor to run requests concurrently
    with ThreadPoolExecutor(max_workers=min(len(nodes_to_query), 10)) as executor:
        # Submit all requests concurrently
        future_to_node = {executor.submit(fetch_node_last_finalized_batch, node, app_name): node
                          for node in nodes_to_query}

        # Collect results as they complete
        for future in future_to_node:
            try:
                batch_record = future.result()
                if batch_record.get("index", 0) > last_finalized_batch_record.get("index", 0):
                    last_finalized_batch_record = batch_record
            except Exception:
                continue  # Skip any unexpected thread-level exceptions

    return last_finalized_batch_record