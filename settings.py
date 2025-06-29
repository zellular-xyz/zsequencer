from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings

MODE_DEV = "dev"
MODE_PROD = "prod"
MODE_TEST = "test"
SIMULATION_MODES = [MODE_DEV, MODE_TEST]


class NodeConfig(BaseSettings):
    version: str = Field(default="v0.0.19")
    nodes_info_sync_border: int = Field(default=5)

    nodes_source: str = Field(default="file")

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

    snapshot_chunk_size_kb: int = Field(default=1000)
    remove_chunk_border: int = Field(default=2)

    sync_interval: float = Field(default=30.0)
    finalization_time_border: int = Field(default=120)
    aggregation_timeout: int = Field(default=5)
    fetch_apps_and_nodes_interval: float = Field(default=60.0)

    bandwidth_kb_per_window: float = Field(default=10_000)
    push_rate_limit_window_seconds: int = Field(default=1)

    max_batch_size_kb: float = Field(default=5)

    init_sequencer_id: str = Field(default="")
    threshold_percent: int = Field(default=100)

    bls_key_file: str = Field(default="")
    ecdsa_key_file: str = Field(default="")
    bls_key_password: str = Field(default="")
    ecdsa_key_password: str = Field(default="")

    sabotage_config_file: str = Field(default="")
    sabotage_simulation: bool = Field(default=False)

    register_operator: bool = Field(default=False)
    register_socket: str = Field(default="")

    mode: Literal["dev", "prod", "test"] = Field(default=MODE_PROD)

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO"
    )

    remote_host_checker_base_url: str = Field(
        default="https://portchecker.io/api/{host}/{port}"
    )
    check_reachability_of_node_url: bool = Field(default=True)

    sequencer_setup_deadline_time_in_seconds: int = Field(default=20)

    class Config:
        env_prefix = "ZSEQUENCER_"
