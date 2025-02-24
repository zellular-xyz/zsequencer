from enum import Enum
from typing import Any, Dict

from pydantic import BaseModel


# Todo: handle aggregated_public_key type
class NetworkState(BaseModel):
    tag: int
    timestamp: int
    nodes: Dict
    aggregated_public_key: Any
    total_stake: float


class NodeSource(Enum):
    FILE = "file"
    EIGEN_LAYER = "eigenlayer"
    NODES_REGISTRY = "historical_nodes_registry"


def get_node_source(value: str) -> NodeSource | None:
    try:
        return NodeSource(value)
    except ValueError:
        return None
