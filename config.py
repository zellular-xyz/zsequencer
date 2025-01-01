"""
Configuration functions for the ZSequencer.
"""

import cProfile
import functools
import json
import os
import sys
import pstats
import time
import requests
import utils
from random import randbytes
from tenacity import retry, stop_after_attempt, wait_fixed

from historical_nodes_registry import NodesRegistryClient
from schema import NetworkState, NodeSource, get_node_source
from typing import Any, List, Dict, Optional
from urllib.parse import urlparse

from eigensdk.crypto.bls import attestation
from web3 import Account
from eigensdk.chainio.clients.builder import BuildAllConfig, build_all
from common.logger import zlogger


class Config:
    _instance = None

    def __init__(self):
        self.APPS = None
        self.IS_SYNCING = None
        self.THRESHOLD_PERCENT = None
        self.INIT_SEQUENCER_ID = None
        self.API_BATCHES_LIMIT = None
        self.FETCH_APPS_AND_NODES_INTERVAL = None
        self.AGGREGATION_TIMEOUT = None
        self.FINALIZATION_TIME_BORDER = None
        self.SYNC_INTERVAL = None
        self.SEND_BATCH_INTERVAL = None
        self.REMOVE_CHUNK_BORDER = None
        self.SNAPSHOT_CHUNK = None
        self.PORT = None
        self.NODE = {}
        self.HISTORICAL_NETWORK_STATE: Dict[int, NetworkState] = {}
        self.NETWORK_STATUS_TAG = None
        self.NODE_SOURCE = None
        self.ADDRESS = None
        self.OPERATOR_STATE_RETRIEVER = None
        self.REGISTRY_COORDINATOR = None
        self.RPC_NODE = None
        self.SUBGRAPH_URL = None
        self.SNAPSHOT_PATH = None
        self.APPS_FILE = None
        self.HISTORICAL_NODES_REGISTRY = None
        self.NODES_FILE = None
        self.NODES_INFO_SYNC_BORDER = None
        self.HEADERS = None
        self.VERSION = None
        self.BLS_KEY_STORE_PATH = None
        self.ECDSA_KEY_STORE_PATH = None
        self.BLS_KEY_PASSWORD = None
        self.ECDSA_KEY_PASSWORD = None
        self.REGISTER_OPERATOR = None

    def __new__(cls) -> "Config":
        if cls._instance is None:
            cls._instance = super(Config, cls).__new__(cls)
            cls._instance._load_environment_variables()
            cls._instance._init_network_config()
        return cls._instance

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(5))
    def get_network_state(self, tag: int) -> NetworkState:
        if tag in self.HISTORICAL_NETWORK_STATE:
            return self.HISTORICAL_NETWORK_STATE.get(tag)

        nodes_data: Dict[str, Dict[str, Any]] = {}
        if self.NODE_SOURCE == NodeSource.FILE:
            nodes_data = utils.get_file_content(self.NODES_FILE)
        elif self.NODE_SOURCE == NodeSource.EIGEN_LAYER:
            nodes_data = utils.get_eigen_network_info(sub_graph_socket=self.SUBGRAPH_URL,
                                                      block_number=tag)
        elif self.NODE_SOURCE == NodeSource.NODES_REGISTRY:
            nodes_data = utils.fetch_historical_nodes_registry_data(
                nodes_registry_socket=self.HISTORICAL_NODES_REGISTRY, timestamp=tag)

        for address, node_data in nodes_data.items():
            public_key_g2: str = node_data["public_key_g2"]
            node_data["public_key_g2"] = attestation.new_zero_g2_point()
            node_data["public_key_g2"].setStr(public_key_g2.encode("utf-8"))

        aggregated_public_key = utils.get_aggregated_public_key(nodes_data)
        total_stake = sum([node['stake'] for node in nodes_data.values()])

        network_state = NetworkState(tag=tag,
                                     nodes=nodes_data,
                                     aggregated_public_key=aggregated_public_key,
                                     total_stake=total_stake)

        self.HISTORICAL_NETWORK_STATE[tag] = network_state
        return network_state

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(5))
    def fetch_tag(self):
        if self.NODE_SOURCE == NodeSource.EIGEN_LAYER:
            self.NETWORK_STATUS_TAG = utils.fetch_eigen_layer_last_block_number(sub_graph_socket=self.SUBGRAPH_URL)
        elif self.NODE_SOURCE == NodeSource.NODES_REGISTRY:
            self.NETWORK_STATUS_TAG = utils.get_nodes_registry_last_tag()
        elif self.NODE_SOURCE == NodeSource.FILE:
            self.NETWORK_STATUS_TAG = 0

    def fetch_network_state(self):
        """Fetch the latest network tag and nodes state and update current nodes info and sequencer"""

        try:
            self.fetch_tag()
        except:
            zlogger.error('Unable to fetch latest network tag')
            return

        try:
            network_state = self.get_network_state(tag=self.NETWORK_STATUS_TAG)
        except:
            zlogger.error('Unable to get network state with tag {}'.format(self.NETWORK_STATUS_TAG))
            return

        nodes_data = network_state.nodes
        sequencer_id = self.SEQUENCER['id']

        self.NODE.update(nodes_data[self.ADDRESS])
        self.SEQUENCER.update(nodes_data[sequencer_id])

        return nodes_data

    def register_operator(self, ecdsa_private_key, bls_key_pair) -> None:
        config = BuildAllConfig(
            eth_http_url=self.RPC_NODE,
            registry_coordinator_addr=self.REGISTRY_COORDINATOR,
            operator_state_retriever_addr=self.OPERATOR_STATE_RETRIEVER,
        )

        clients = build_all(config, ecdsa_private_key)
        clients.avs_registry_writer.register_operator_in_quorum_with_avs_registry_coordinator(
            operator_ecdsa_private_key=ecdsa_private_key,
            operator_to_avs_registration_sig_salt=randbytes(32),
            operator_to_avs_registration_sig_expiry=int(time.time()) + 60,
            bls_key_pair=bls_key_pair,
            quorum_numbers=[0],
            socket=os.getenv("ZSEQUENCER_REGISTER_SOCKET"),
        )

    def init_sequencer(self) -> None:
        """Finds the initial sequencer id."""
        sequencers_stake: dict[str, Any] = {
            node_id: 0 for node_id in list(self.NODES.keys())
        }
        for node_id in list(self.NODES.keys()):
            if node_id == self.NODE["id"]:
                continue
            url: str = f"{self.NODES[node_id]['socket']}/node/state"
            try:
                response = requests.get(url=url, headers=self.HEADERS, timeout=1).json()
                if response["data"]["version"] != self.VERSION:
                    continue
                sequencer_id = response["data"]["sequencer_id"]
                sequencers_stake[sequencer_id] += self.NODES[node_id]["stake"]
            except Exception:
                zlogger.warning(f"Unable to get state from {node_id}")
        max_stake_id = max(sequencers_stake, key=lambda k: sequencers_stake[k])
        sequencers_stake[max_stake_id] += self.NODE["stake"]
        if 100 * sequencers_stake[max_stake_id] / self.TOTAL_STAKE >= self.THRESHOLD_PERCENT and \
                sequencers_stake[max_stake_id] > self.NODE["stake"]:
            self.update_sequencer(max_stake_id)
        else:
            self.update_sequencer(self.INIT_SEQUENCER_ID)

    def _load_environment_variables(self):
        self.NODE_SOURCE = get_node_source(os.getenv("ZSEQUENCER_NODES_SOURCE"))
        utils.validate_env_variables(self.NODE_SOURCE)

        self.VERSION = "v0.0.12"
        self.HEADERS: dict[str, Any] = {
            "Content-Type": "application/json",
            "Version": self.VERSION
        }
        self.NODES_INFO_SYNC_BORDER = 5  # in seconds
        self.IS_SYNCING: bool = True
        self.NODES_FILE: str = os.getenv("ZSEQUENCER_NODES_FILE", "./nodes.json")
        self.HISTORICAL_NODES_REGISTRY = os.getenv("ZSEQUENCER_HISTORICAL_NODES_REGISTRY", "")
        self.APPS_FILE: str = os.getenv("ZSEQUENCER_APPS_FILE", "./apps.json")
        self.SNAPSHOT_PATH: str = os.getenv("ZSEQUENCER_SNAPSHOT_PATH", "./data/")

        self.SUBGRAPH_URL = os.getenv('ZSEQUENCER_SUBGRAPH_URL', '')
        self.RPC_NODE = os.getenv('ZSEQUENCER_RPC_NODE', '')
        self.REGISTRY_COORDINATOR = os.getenv('ZSEQUENCER_REGISTRY_COORDINATOR', '')
        self.OPERATOR_STATE_RETRIEVER = os.getenv('ZSEQUENCER_OPERATOR_STATE_RETRIEVER', '')

        self.PORT: int = int(os.getenv("ZSEQUENCER_PORT", "6000"))

        self.SNAPSHOT_CHUNK: int = int(os.getenv("ZSEQUENCER_SNAPSHOT_CHUNK", "1000"))
        self.REMOVE_CHUNK_BORDER: int = int(os.getenv("ZSEQUENCER_REMOVE_CHUNK_BORDER", "2"))

        self.SEND_BATCH_INTERVAL: float = float(os.getenv("ZSEQUENCER_SEND_TXS_INTERVAL", "5"))
        self.SYNC_INTERVAL: float = float(os.getenv("ZSEQUENCER_SYNC_INTERVAL", "30"))
        self.FINALIZATION_TIME_BORDER: int = int(os.getenv("ZSEQUENCER_FINALIZATION_TIME_BORDER", "120"))
        self.AGGREGATION_TIMEOUT: int = int(os.getenv("ZSEQUENCER_SIGNATURES_AGGREGATION_TIMEOUT", "5"))
        self.FETCH_APPS_AND_NODES_INTERVAL: int = int(os.getenv("ZSEQUENCER_FETCH_APPS_AND_NODES_INTERVAL", "60"))
        self.API_BATCHES_LIMIT: int = int(os.getenv("ZSEQUENCER_API_BATCHES_LIMIT", "100"))
        self.INIT_SEQUENCER_ID: str = os.getenv("ZSEQUENCER_INIT_SEQUENCER_ID")
        self.THRESHOLD_PERCENT: int = float(os.getenv("ZSEQUENCER_THRESHOLD_PERCENT", '100'))

        self.BLS_KEY_STORE_PATH: str = os.getenv("ZSEQUENCER_BLS_KEY_FILE", "")
        self.ECDSA_KEY_STORE_PATH: str = os.getenv("ZSEQUENCER_ECDSA_KEY_FILE", "")
        self.BLS_KEY_PASSWORD: str = os.getenv("ZSEQUENCER_BLS_KEY_PASSWORD", "")
        self.ECDSA_KEY_PASSWORD: str = os.getenv("ZSEQUENCER_ECDSA_KEY_PASSWORD", "")

        self.REGISTER_OPERATOR = os.getenv("ZSEQUENCER_REGISTER_OPERATOR") == 'true'
        bls_key_pair: attestation.KeyPair = attestation.KeyPair.read_from_file(self.BLS_KEY_STORE_PATH,
                                                                               self.BLS_KEY_PASSWORD)

        with open(self.ECDSA_KEY_STORE_PATH, 'r') as f:
            encrypted_json: str = json.loads(f.read())
        ecdsa_private_key: str = Account.decrypt(encrypted_json, self.ECDSA_KEY_PASSWORD)
        self.ADDRESS = Account.from_key(ecdsa_private_key).address.lower()

        self.fetch_network_state()

        if self.ADDRESS in self.HISTORICAL_NETWORK_STATE[self.NETWORK_STATUS_TAG].nodes:
            self.NODE = self.HISTORICAL_NETWORK_STATE[self.NETWORK_STATUS_TAG].nodes[self.ADDRESS]
            public_key_g2: str = self.NODE["public_key_g2"].getStr(10).decode('utf-8')
            public_key_g2_from_private: str = bls_key_pair.pub_g2.getStr(10).decode('utf-8')
            error_msg = "the bls key pair public key does not match public of the node in the nodes list"
            assert public_key_g2 == public_key_g2_from_private, error_msg
        else:
            if self.REGISTER_OPERATOR:
                self.register_operator(ecdsa_private_key, bls_key_pair)
                zlogger.warning("Operator registration transaction sent.")
            zlogger.warning("Operator not found in the nodes' list")
            sys.exit()

        self.NODE.update({
            'ecdsa_private_key': ecdsa_private_key,
            'bls_key_pair': bls_key_pair
        })

        os.makedirs(self.SNAPSHOT_PATH, exist_ok=True)

        if self.PORT != urlparse(self.NODE['socket']).port:
            zlogger.warning(
                f"The node port in the .env file does not match the node port provided by {self.NODE_SOURCE.value}.")
            sys.exit()

    def _init_network_config(self):
        self.fetch_network_state()
        self.init_sequencer()

        if self.SEQUENCER["id"] == self.NODE["id"]:
            self.IS_SYNCING = False

        self.APPS: dict[str, dict[str, Any]] = utils.get_file_content(self.APPS_FILE)

        for app_name in self.APPS:
            snapshot_path: str = os.path.join(self.SNAPSHOT_PATH, self.VERSION, app_name)
            os.makedirs(snapshot_path, exist_ok=True)

    @property
    def nodes_last_state(self):
        return self.HISTORICAL_NETWORK_STATE[self.NETWORK_STATUS_TAG].nodes

    def update_sequencer(self, sequencer_id: str | None) -> None:
        """Update the sequencer configuration."""
        if sequencer_id:
            self.SEQUENCER = self.NODES[sequencer_id]

    # TODO: remove
    @staticmethod
    def profile_function(output_file: str) -> Any:
        """Decorator to profile the execution of a function."""

        def decorator(func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                profiler = cProfile.Profile()
                profiler.enable()
                try:
                    result = func(*args, **kwargs)
                finally:
                    profiler.disable()
                    with open(
                            file=f"{zconfig.NODE['port']}_{output_file}",
                            mode="a",
                            encoding="utf-8",
                    ) as file:
                        ps = pstats.Stats(profiler, stream=file)
                        ps.strip_dirs().sort_stats("cumulative").print_stats()
                return result

            return wrapper

        return decorator


zconfig: Config = Config()
