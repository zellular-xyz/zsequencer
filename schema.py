import os
from enum import Enum
from typing import Any, Dict

from pydantic import BaseModel


# Todo: handle aggregated_public_key type
class NetworkState(BaseModel):
    tag: int
    timestamp: int
    nodes: Dict
    aggregated_public_key: Any
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


class NodeConfig(BaseModel):
    VERSION: str
    HEADERS: Dict[str, Any]
    NODES_INFO_SYNC_BORDER: int

    NODE_SOURCE: NodeSource
    NODES_FILE: str
    HISTORICAL_NODES_REGISTRY: str
    APPS_FILE: str
    SNAPSHOT_PATH: str

    SUBGRAPH_URL: str
    RPC_NODE: str
    REGISTRY_COORDINATOR: str
    OPERATOR_STATE_RETRIEVER: str

    PORT: int
    SNAPSHOT_CHUNK: int
    REMOVE_CHUNK_BORDER: int

    SEND_BATCH_INTERVAL: float
    SYNC_INTERVAL: float
    FINALIZATION_TIME_BORDER: int
    AGGREGATION_TIMEOUT: int
    FETCH_APPS_AND_NODES_INTERVAL: float
    API_BATCHES_LIMIT: int

    INIT_SEQUENCER_ID: str
    THRESHOLD_PERCENT: int

    BLS_KEY_STORE_PATH: str
    ECDSA_KEY_STORE_PATH: str
    BLS_KEY_PASSWORD: str
    ECDSA_KEY_PASSWORD: str

    REGISTER_OPERATOR: bool

    @classmethod
    def from_env(cls):
        return cls(
            VERSION="v0.0.13",
            HEADERS={
                "Content-Type": "application/json",
                "Version": os.getenv("ZSEQUENCER_VERSION", "v0.0.13")
            },
            NODES_INFO_SYNC_BORDER=5,  # You can adjust if needed
            NODE_SOURCE=get_node_source(os.getenv("ZSEQUENCER_NODES_SOURCE")),
            NODES_FILE=os.getenv("ZSEQUENCER_NODES_FILE"),
            HISTORICAL_NODES_REGISTRY=os.getenv("ZSEQUENCER_HISTORICAL_NODES_REGISTRY", ""),
            APPS_FILE=os.getenv("ZSEQUENCER_APPS_FILE", "./apps.json"),
            SNAPSHOT_PATH=os.getenv("ZSEQUENCER_SNAPSHOT_PATH", "./data/"),
            SUBGRAPH_URL=os.getenv("ZSEQUENCER_SUBGRAPH_URL", ''),
            RPC_NODE=os.getenv("ZSEQUENCER_RPC_NODE", ''),
            REGISTRY_COORDINATOR=os.getenv("ZSEQUENCER_REGISTRY_COORDINATOR", ''),
            OPERATOR_STATE_RETRIEVER=os.getenv("ZSEQUENCER_OPERATOR_STATE_RETRIEVER", ''),
            PORT=int(os.getenv("ZSEQUENCER_PORT", "6000")),
            SNAPSHOT_CHUNK=int(os.getenv("ZSEQUENCER_SNAPSHOT_CHUNK", "1000")),
            REMOVE_CHUNK_BORDER=int(os.getenv("ZSEQUENCER_REMOVE_CHUNK_BORDER", "2")),
            SEND_BATCH_INTERVAL=float(os.getenv("ZSEQUENCER_SEND_TXS_INTERVAL", "5")),
            SYNC_INTERVAL=float(os.getenv("ZSEQUENCER_SYNC_INTERVAL", "30")),
            FINALIZATION_TIME_BORDER=int(os.getenv("ZSEQUENCER_FINALIZATION_TIME_BORDER", "120")),
            AGGREGATION_TIMEOUT=int(os.getenv("ZSEQUENCER_SIGNATURES_AGGREGATION_TIMEOUT", "5")),
            FETCH_APPS_AND_NODES_INTERVAL=float(os.getenv("ZSEQUENCER_FETCH_APPS_AND_NODES_INTERVAL", "60")),
            API_BATCHES_LIMIT=int(os.getenv("ZSEQUENCER_API_BATCHES_LIMIT", "100")),
            INIT_SEQUENCER_ID=os.getenv("ZSEQUENCER_INIT_SEQUENCER_ID"),
            THRESHOLD_PERCENT=int(os.getenv("ZSEQUENCER_THRESHOLD_PERCENT", '100')),
            BLS_KEY_STORE_PATH=os.getenv("ZSEQUENCER_BLS_KEY_FILE", ""),
            ECDSA_KEY_STORE_PATH=os.getenv("ZSEQUENCER_ECDSA_KEY_FILE", ""),
            BLS_KEY_PASSWORD=os.getenv("ZSEQUENCER_BLS_KEY_PASSWORD", ""),
            ECDSA_KEY_PASSWORD=os.getenv("ZSEQUENCER_ECDSA_KEY_PASSWORD", ""),
            REGISTER_OPERATOR=os.getenv("ZSEQUENCER_REGISTER_OPERATOR") == 'true')
