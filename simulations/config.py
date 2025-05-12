import json
import os
import shutil
from typing import Any
from typing import Dict
from typing import List

from eigensdk.crypto.bls import attestation
from pydantic import BaseModel
from pydantic import Field
from web3 import Account

VERSION = "v0.0.14"

BASE_NODE_PORT = 6005
BASE_PROXY_PORT = 7001


class NodeInfo(BaseModel):
    id: str
    pubkeyG2_X: tuple
    pubkeyG2_Y: tuple
    address: str
    socket: str
    stake: int


SnapShotType = Dict[str, NodeInfo]


class Keys(BaseModel):
    bls_private_key: str
    bls_key_pair: Any
    ecdsa_private_key: str


class KeyData(BaseModel):
    keys: Keys
    address: str


class ExecutionData(BaseModel):
    env_variables: Dict


class SimulationConfig(BaseModel):
    NUM_INSTANCES: int = Field(3, description="Number of instances")
    HOST: str = Field("http://127.0.0.1", description="Host address")
    BASE_PORT: int = Field(BASE_NODE_PORT, description="Base port number")
    PROXY_BASE_PORT: int = Field(BASE_PROXY_PORT, description="Base proxy port number")
    THRESHOLD_PERCENT: int = Field(42, description="Threshold percentage")
    DST_DIR: str = Field("/tmp/zellular_dev_net", description="Destination directory")
    HISTORICAL_NODES_REGISTRY_HOST: str = Field("localhost", description="Historical nodes registry host")
    HISTORICAL_NODES_REGISTRY_PORT: int = Field(8000, description="Historical nodes registry port")
    HISTORICAL_NODES_REGISTRY_SOCKET: str = Field(None, description="Socket for historical nodes registry", )

    ZSEQUENCER_SNAPSHOT_CHUNK_SIZE_KB: int = Field(default=1000, description="Snapshot chunk size in kilo-bytes")
    ZSEQUENCER_BANDWIDTH_KB_PER_WINDOW: float = Field(default=10_000,
                                                      description="sequencer bandwidth in unit of kilo-bytes in a single window")
    ZSEQUENCER_PUSH_RATE_LIMIT_WINDOW_SECONDS: int = Field(default=1,
                                                           description="timing window in seconds to control nodes pushing batches")
    ZSEQUENCER_MAX_BATCH_SIZE_KB: float = Field(default=5,
                                                description="maximum allowed size of a single batch in kilo-bytes")
    ZSEQUENCER_REMOVE_CHUNK_BORDER: int = Field(3, description="Chunk border for ZSequencer removal")
    ZSEQUENCER_SYNC_INTERVAL: float = Field(0.05, description="Sync interval for ZSequencer")
    ZSEQUENCER_FINALIZATION_TIME_BORDER: int = Field(10, description="Finalization time border for ZSequencer")
    ZSEQUENCER_SIGNATURES_AGGREGATION_TIMEOUT: int = Field(5, description="Timeout for signatures aggregation")
    ZSEQUENCER_FETCH_APPS_AND_NODES_INTERVAL: int = Field(60, description="Interval to fetch apps and nodes")
    ZSEQUENCER_NODES_SOURCE: str = Field("file", description="Source for nodes in ZSequencer", )
    APP_NAME: str = Field("simple_app", description="Name of the application")
    TIMESERIES_NODES_COUNT: List[int] = Field([3, 4, 6],
                                              description="count of nodes available on network at different states")
    PROXY_SERVER_WORKERS_COUNT: int = Field(4, description="The number of workers count for proxy server")
    MODE: str = Field("dev", description="The stage mode of running node can be set on dev, test, prod")

    # Sequencer Malfunction config
    OUT_OF_REACH_SIMULATION: bool = Field(False, description="out of reach simulation flag")

    CHECK_REACHABILITY_OF_NODE_URL: bool = Field(False, description="check reachability of node flag")

    class Config:
        validate_assignment = True

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.HISTORICAL_NODES_REGISTRY_SOCKET = (
            f"{self.HISTORICAL_NODES_REGISTRY_HOST}:{self.HISTORICAL_NODES_REGISTRY_PORT}"
        )

    def get_snapshot_dir(self, node_idx):
        return os.path.join(self.DST_DIR, f'db{node_idx}')

    def get_bls_key_file(self, node_idx):
        return os.path.join(self.DST_DIR, f'bls_key{node_idx}.json')

    @staticmethod
    def get_bls_key_passwd(node_idx):
        return f'a{node_idx}'

    def get_ecdsa_key_file(self, node_idx):
        return os.path.join(self.DST_DIR, f'ecdsa_key{node_idx}.json')

    @staticmethod
    def get_ecdsa_key_passwd(node_idx):
        return f'b{node_idx}'

    @property
    def apps_file(self):
        return os.path.join(self.DST_DIR, "apps.json")

    @property
    def sabotage_timeseries_nodes_state_file(self):
        return os.path.join(self.DST_DIR, "sabotage_nodes_state.json")

    @property
    def nodes_file(self):
        return os.path.join(self.DST_DIR, "nodes.json")

    def get_proxy_port(self, node_idx):
        return self.PROXY_BASE_PORT + node_idx

    def prepare_node(self, node_idx: int, keys: Keys):
        data_dir: str = self.get_snapshot_dir(node_idx=node_idx)
        if os.path.exists(data_dir):
            shutil.rmtree(data_dir)

        bls_key_pair: attestation.KeyPair = attestation.new_key_pair_from_string(keys.bls_private_key)
        bls_key_pair.save_to_file(self.get_bls_key_file(node_idx=node_idx), self.get_bls_key_passwd(node_idx))

        encrypted_json = Account.encrypt(keys.ecdsa_private_key, self.get_ecdsa_key_passwd(node_idx))
        with open(self.get_ecdsa_key_file(node_idx), 'w') as f:
            f.write(json.dumps(encrypted_json))

    def to_dict(self, node_idx: int, sequencer_initial_address: str) -> dict:
        return {
            "ZSEQUENCER_APPS_FILE": self.apps_file,
            "ZSEQUENCER_NODES_FILE": self.nodes_file,
            "ZSEQUENCER_HISTORICAL_NODES_REGISTRY": self.HISTORICAL_NODES_REGISTRY_SOCKET,
            "ZSEQUENCER_HOST": "localhost",
            "ZSEQUENCER_PORT": str(self.BASE_PORT + node_idx),

            "ZSEQUENCER_REMOVE_CHUNK_BORDER": str(self.ZSEQUENCER_REMOVE_CHUNK_BORDER),
            "ZSEQUENCER_THRESHOLD_PERCENT": str(self.THRESHOLD_PERCENT),
            "ZSEQUENCER_SYNC_INTERVAL": str(self.ZSEQUENCER_SYNC_INTERVAL),
            "ZSEQUENCER_FINALIZATION_TIME_BORDER": str(self.ZSEQUENCER_FINALIZATION_TIME_BORDER),
            "ZSEQUENCER_SIGNATURES_AGGREGATION_TIMEOUT": str(self.ZSEQUENCER_SIGNATURES_AGGREGATION_TIMEOUT),
            "ZSEQUENCER_FETCH_APPS_AND_NODES_INTERVAL": str(self.ZSEQUENCER_FETCH_APPS_AND_NODES_INTERVAL),
            "ZSEQUENCER_INIT_SEQUENCER_ID": sequencer_initial_address,
            "ZSEQUENCER_NODES_SOURCE": self.ZSEQUENCER_NODES_SOURCE,
            "ZSEQUENCER_MODE": self.MODE,
            # rate limiting
            "ZSEQUENCER_BANDWIDTH_KB_PER_WINDOW": str(self.ZSEQUENCER_BANDWIDTH_KB_PER_WINDOW),
            "ZSEQUENCER_PUSH_RATE_LIMIT_WINDOW_SECONDS": str(self.ZSEQUENCER_PUSH_RATE_LIMIT_WINDOW_SECONDS),
            "ZSEQUENCER_MAX_BATCH_SIZE_KB": str(self.ZSEQUENCER_MAX_BATCH_SIZE_KB),
            # SnapShot
            "ZSEQUENCER_SNAPSHOT_PATH": os.path.join(self.DST_DIR, f"db_{node_idx}"),
            "ZSEQUENCER_SNAPSHOT_CHUNK_SIZE_KB": str(self.ZSEQUENCER_SNAPSHOT_CHUNK_SIZE_KB),
            # Encryption Files Configs
            "ZSEQUENCER_BLS_KEY_FILE": os.path.join(self.DST_DIR, f"bls_key{node_idx}.json"),
            "ZSEQUENCER_BLS_KEY_PASSWORD": f'a{node_idx}',
            "ZSEQUENCER_ECDSA_KEY_FILE": os.path.join(self.DST_DIR, f"ecdsa_key{node_idx}.json"),
            "ZSEQUENCER_ECDSA_KEY_PASSWORD": f'b{node_idx}',
            # Proxy config
            "ZSEQUENCER_PROXY_HOST": "localhost",
            "ZSEQUENCER_PROXY_PORT": str(self.get_proxy_port(node_idx)),
            "ZSEQUENCER_PROXY_FLUSH_THRESHOLD_VOLUME": str(2000),
            "ZSEQUENCER_PROXY_FLUSH_THRESHOLD_TIMEOUT": "0.1",
            # Sequencer MalFunction Simulation config
            "ZSEQUENCER_SEQUENCER_SABOTAGE_SIMULATION_OUT_OF_REACH_SIMULATION": str(
                self.OUT_OF_REACH_SIMULATION).lower(),
            "ZSEQUENCER_SEQUENCER_SABOTAGE_SIMULATION_TIMESERIES_NODES_STATE_FILE": self.sabotage_timeseries_nodes_state_file,
            # Reachability Flag
            "ZSEQUENCER_CHECK_REACHABILITY_OF_NODE_URL": str(self.CHECK_REACHABILITY_OF_NODE_URL).lower()
        }
