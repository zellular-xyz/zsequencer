from pydantic import Field
from pydantic_settings import BaseSettings


class NodeConfig(BaseSettings):
    version: str = Field(default="v0.0.13")
    nodes_info_sync_border: int = Field(default=5)

    node_source: str = Field(default="file")

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
