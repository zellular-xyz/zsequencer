from enum import Enum
from typing import Any

from pydantic import BaseModel


# TODO: handle aggregated_public_key type
class NetworkState(BaseModel):
    tag: int
    timestamp: int
    nodes: dict[str, dict[str, Any]]
    aggregated_public_key: Any
    total_stake: float

    def get_nodes_with_role(self, role) -> dict[str, dict[str, Any]]:
        return {
            address: node_data
            for address, node_data in self.nodes.items()
            if role in node_data["roles"]
        }

    @property
    def sequencing_nodes(self) -> dict[str, dict[str, Any]]:
        return self.get_nodes_with_role("sequencing")

    @property
    def posting_nodes(self) -> dict[str, dict[str, Any]]:
        return self.get_nodes_with_role("posting")

    @property
    def attesting_nodes(self) -> dict[str, dict[str, Any]]:
        return {
            address: node_data
            for address, node_data in self.nodes.items()
            if node_data["stake"] > 0
        }


class NodeSource(Enum):
    FILE = "file"
    EIGEN_LAYER = "eigenlayer"
    NODES_REGISTRY = "historical_nodes_registry"


def get_node_source(value: str) -> NodeSource | None:
    try:
        return NodeSource(value)
    except ValueError:
        return None
