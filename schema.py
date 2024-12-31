from enum import Enum

from pydantic import BaseModel
from typing import Dict


class NetworkState(BaseModel):
    tag: int
    nodes: Dict
    aggregated_public_key: str
    total_stake: int


class NodeSource(Enum):
    FILE = "file"
    EIGEN_LAYER = "eigenlayer"
    NODES_REGISTRY = "historical_nodes_registry"


def get_node_source(value: str) -> NodeSource | None:
    try:
        return NodeSource(value)
    except ValueError:
        return None
