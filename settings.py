import os
from typing import Dict, Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings

from schema import NodeSource, get_node_source


class ProxyConfig(BaseSettings):
    host: str = Field(default="localhost")
    port: int = Field(default=6002)

    class Config:
        env_prefix = "ZSEQUENCER_PROXY_"


class NodeConfig(BaseSettings):
    version: str = Field(default="v0.0.13")
    headers: Dict[str, Any] = Field(default_factory=lambda: {
        "Content-Type": "application/json",
        "Version": os.getenv("ZSEQUENCER_VERSION", "v0.0.13")
    })
    nodes_info_sync_border: int = Field(default=5)

    node_source: NodeSource = Field(default_factory=lambda: get_node_source(os.getenv("ZSEQUENCER_NODES_SOURCE")))
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

    @field_validator("register_operator", mode="before")
    @classmethod
    def parse_register_operator(cls, v):
        """Ensure register_operator is always a boolean."""
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.lower() == "true"
        raise ValueError(f"Invalid boolean value for register_operator: {v}")
