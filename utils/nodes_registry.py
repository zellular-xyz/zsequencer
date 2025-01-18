import time
from typing import Optional, Dict, Any

from utils.historical_nodes_registry.client import NodesRegistryClient


def fetch_historical_nodes_registry_data(nodes_registry_socket: str, timestamp: Optional[int]) -> Dict[str, Any]:
    snapshot = NodesRegistryClient(nodes_registry_socket).get_network_snapshot(timestamp=timestamp)
    snapshot_data = {address: node_info.dict() for address, node_info in snapshot.items()}
    return snapshot_data


def get_nodes_registry_last_tag() -> int:
    return int(time.time())
