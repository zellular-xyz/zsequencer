from pydantic import Field
from pydantic_settings import BaseSettings
from typing import Literal

MODE_DEV = "dev"
MODE_PROD = "prod"
MODE_TEST = "test"
SIMULATION_MODES = [MODE_DEV, MODE_TEST]


class SequencerSabotageSimulation(BaseSettings):
    out_of_reach_simulation: bool = Field(default=False)
    in_reach_seconds: int = Field(default=20)
    out_of_reach_seconds: int = Field(default=20)

    class Config:
        env_prefix = "ZSEQUENCER_SEQUENCER_SABOTAGE_SIMULATION_"


class NodeConfig(BaseSettings):
    version: str = Field(default="v0.0.15")
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
    snapshot_chunk: int = Field(default=1000)
    remove_chunk_border: int = Field(default=2)

    sync_interval: float = Field(default=30.0)
    finalization_time_border: int = Field(default=120)
    aggregation_timeout: int = Field(default=5)
    fetch_apps_and_nodes_interval: float = Field(default=60.0)
    api_batches_limit: int = Field(default=100000)

    bandwidth_kb_per_window: float = Field(default=10_000)
    push_rate_limit_window_seconds: int = Field(default=1)

    max_batch_size_kb: float = Field(default=5)

    init_sequencer_id: str = Field(default="")
    threshold_percent: int = Field(default=100)

    bls_key_file: str = Field(default="")
    ecdsa_key_file: str = Field(default="")
    bls_key_password: str = Field(default="")
    ecdsa_key_password: str = Field(default="")

    register_operator: bool = Field(default=False)
    register_socket: str = Field(default="")

    mode: Literal["dev", "prod", "test"] = Field(default=MODE_PROD)

    max_missed_batches_to_pick: int = Field(default=10)
    # sequencer_sabotage_simulation: SequencerSabotageSimulation = Field(default_factory=SequencerSabotageSimulation)

    class Config:
        env_prefix = "ZSEQUENCER_"
