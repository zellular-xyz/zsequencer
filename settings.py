import os
from typing import Dict, Any, Optional

from pydantic import Field, field_validator, AfterValidator
from pydantic_settings import BaseSettings

from schema import NodeSource, get_node_source


class ProxyConfig(BaseSettings):
    host: str = Field(default="localhost")
    port: int = Field(default=6002)

    class Config:
        env_prefix = "ZSEQUENCER_PROXY_"


def validate_headers(headers: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure the headers dictionary contains the correct Content-Type and Version."""
    if "Content-Type" not in headers:
        headers["Content-Type"] = "application/json"
    if "Version" not in headers:
        headers["Version"] = os.getenv("ZSEQUENCER_VERSION", "v0.0.13")
    return headers


def validate_node_source(node_source: Optional['NodeSource']) -> 'NodeSource':
    """Ensure the node_source is properly initialized."""
    if node_source is None:
        # Fallback to a default NodeSource if the environment variable is not set
        return get_node_source(os.getenv("ZSEQUENCER_NODES_SOURCE"))
    return node_source


class NodeConfig(BaseSettings):
    version: str = Field(default="v0.0.13")
    headers: Dict[str, Any] = Field(
        default_factory=lambda: {
            "Content-Type": "application/json",
            "Version": os.getenv("ZSEQUENCER_VERSION", "v0.0.13")
        },
        after_validator=AfterValidator(validate_headers))

    nodes_info_sync_border: int = Field(default=5)

    node_source: NodeSource = Field(
        default_factory=lambda: get_node_source(os.getenv("ZSEQUENCER_NODES_SOURCE")),
        after_validator=AfterValidator(validate_node_source)
    )

    nodes_file: str = Field(default="")
    historical_nodes_registry: str = Field(default="")
    apps_file: str = Field(default="./apps.json")
    snapshot_path: str = Field(default="./data/")

    subgraph_url: str = Field(default="")
    rpc_node: str = Field(default="")
    registry_coordinator: str = Field(default="")
    operator_state_retriever: str = Field(default="")

    host: str = Field(default="localhost")
    port: int = Field(default=6001)
    snapshot_chunk: int = Field(default=1000)
    remove_chunk_border: int = Field(default=2)

    send_batch_interval: float = Field(default=5.0)
    sync_interval: float = Field(default=30.0)
    finalization_time_border: int = Field(default=120)
    aggregation_timeout: int = Field(default=5)
    fetch_apps_and_nodes_interval: float = Field(default=60.0)
    api_batches_limit: int = Field(default=100000)

    init_sequencer_id: str = Field(default="")
    threshold_percent: int = Field(default=100)

    bls_key_file: str = Field(default="")
    ecdsa_key_file: str = Field(default="")
    bls_key_password: str = Field(default="")
    ecdsa_key_password: str = Field(default="")

    register_operator: bool = Field(default=False)
    register_socket: str = Field(default="")

    class Config:
        env_prefix = "ZSEQUENCER_"
