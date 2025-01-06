"""
Configuration functions for the ZSequencer.
"""

import cProfile
import functools
import json
import os
import pstats
import sys
import time
from random import randbytes
from typing import Any, Dict
from urllib.parse import urlparse

import requests
from eigensdk.chainio.clients.builder import BuildAllConfig, build_all
from eigensdk.crypto.bls import attestation
from tenacity import retry, stop_after_attempt, wait_fixed
from web3 import Account

import utils
from common.logger import zlogger
from schema import NetworkState, NodeSource, NodeConfig


class Config:
    _instance = None

    def __init__(self, node_config: NodeConfig):
        self.node_config = node_config
        self.HISTORICAL_NETWORK_STATE: Dict[int, NetworkState] = {}
        self.NODE = {}

        self.APPS = {}
        self.NETWORK_STATUS_TAG = None
        self.ADDRESS = None
        self.IS_SYNCING = None

        # Load fields from config
        self.THRESHOLD_PERCENT = node_config.THRESHOLD_PERCENT
        self.INIT_SEQUENCER_ID = node_config.INIT_SEQUENCER_ID
        self.SEQUENCER = {'id': self.INIT_SEQUENCER_ID}
        self.API_BATCHES_LIMIT = node_config.API_BATCHES_LIMIT
        self.FETCH_APPS_AND_NODES_INTERVAL = node_config.FETCH_APPS_AND_NODES_INTERVAL
        self.AGGREGATION_TIMEOUT = node_config.AGGREGATION_TIMEOUT
        self.FINALIZATION_TIME_BORDER = node_config.FINALIZATION_TIME_BORDER
        self.SYNC_INTERVAL = node_config.SYNC_INTERVAL
        self.SEND_BATCH_INTERVAL = node_config.SEND_BATCH_INTERVAL
        self.REMOVE_CHUNK_BORDER = node_config.REMOVE_CHUNK_BORDER
        self.SNAPSHOT_CHUNK = node_config.SNAPSHOT_CHUNK
        self.PORT = node_config.PORT
        self.NODE_SOURCE = node_config.NODE_SOURCE
        self.OPERATOR_STATE_RETRIEVER = node_config.OPERATOR_STATE_RETRIEVER
        self.REGISTRY_COORDINATOR = node_config.REGISTRY_COORDINATOR
        self.RPC_NODE = node_config.RPC_NODE
        self.SUBGRAPH_URL = node_config.SUBGRAPH_URL
        self.SNAPSHOT_PATH = node_config.SNAPSHOT_PATH
        self.APPS_FILE = node_config.APPS_FILE
        self.HISTORICAL_NODES_REGISTRY = node_config.HISTORICAL_NODES_REGISTRY
        self.NODES_FILE = node_config.NODES_FILE
        self.NODES_INFO_SYNC_BORDER = node_config.NODES_INFO_SYNC_BORDER
        self.HEADERS = node_config.HEADERS
        self.VERSION = node_config.VERSION
        self.BLS_KEY_STORE_PATH = node_config.BLS_KEY_STORE_PATH
        self.ECDSA_KEY_STORE_PATH = node_config.ECDSA_KEY_STORE_PATH
        self.BLS_KEY_PASSWORD = node_config.BLS_KEY_PASSWORD
        self.ECDSA_KEY_PASSWORD = node_config.ECDSA_KEY_PASSWORD
        self.REGISTER_OPERATOR = node_config.REGISTER_OPERATOR

        # Init node encryption and networks configurations
        self._init_node()

    @staticmethod
    def get_instance(node_config: NodeConfig):
        if not Config._instance:
            Config._instance = Config(node_config=node_config)
        return Config._instance

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(5))
    def get_network_state(self, tag: int) -> NetworkState:
        if tag in self.HISTORICAL_NETWORK_STATE:
            return self.HISTORICAL_NETWORK_STATE[tag]

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

        self.HISTORICAL_NETWORK_STATE[tag] = NetworkState(tag=tag,
                                                          timestamp=int(time.time()),
                                                          nodes=nodes_data,
                                                          aggregated_public_key=aggregated_public_key,
                                                          total_stake=total_stake)
        return self.HISTORICAL_NETWORK_STATE[tag]

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

        # Todo: properly handle exception on fetching tag and corresponding network state
        self.fetch_tag()
        network_state = self.get_network_state(tag=self.NETWORK_STATUS_TAG)

        nodes_data = network_state.nodes

        self.NODE.update(nodes_data[self.ADDRESS])
        self.SEQUENCER.update(nodes_data[self.SEQUENCER['id']])

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
        current_network_nodes = self.HISTORICAL_NETWORK_STATE[self.NETWORK_STATUS_TAG].nodes
        total_stake = self.HISTORICAL_NETWORK_STATE[self.NETWORK_STATUS_TAG].total_stake

        sequencers_stake: dict[str, Any] = {
            node_id: 0 for node_id in list(current_network_nodes.keys())
        }
        for node_id in list(current_network_nodes.keys()):
            if node_id == self.NODE["id"]:
                continue
            url: str = f"{current_network_nodes[node_id]['socket']}/node/state"
            try:
                response = requests.get(url=url, headers=self.HEADERS, timeout=1).json()
                if response["data"]["version"] != self.VERSION:
                    continue
                sequencer_id = response["data"]["sequencer_id"]
                sequencers_stake[sequencer_id] += current_network_nodes[node_id]["stake"]
            except Exception:
                zlogger.warning(f"Unable to get state from {node_id}")
        max_stake_id = max(sequencers_stake, key=lambda k: sequencers_stake[k])
        sequencers_stake[max_stake_id] += self.NODE["stake"]
        if 100 * sequencers_stake[max_stake_id] / total_stake >= self.THRESHOLD_PERCENT and \
                sequencers_stake[max_stake_id] > self.NODE["stake"]:
            self.update_sequencer(max_stake_id)
        else:
            self.update_sequencer(self.INIT_SEQUENCER_ID)

    def _init_node(self):
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

        self.init_sequencer()
        if self.SEQUENCER["id"] == self.NODE["id"]:
            self.IS_SYNCING = False

        self.APPS = utils.get_file_content(self.APPS_FILE)

        for app_name in self.APPS:
            snapshot_path = os.path.join(self.SNAPSHOT_PATH, self.VERSION, app_name)
            os.makedirs(snapshot_path, exist_ok=True)

    @property
    def last_state(self) -> NetworkState:
        return self.HISTORICAL_NETWORK_STATE[self.NETWORK_STATUS_TAG]

    @property
    def NODES(self):
        return self.last_state.nodes

    @property
    def last_tag(self):
        return self.NETWORK_STATUS_TAG

    @property
    def TOTAL_STAKE(self):
        return self.last_state.total_stake

    @property
    def nodes_last_state(self):
        return {
            "total_stake": self.TOTAL_STAKE,
            "aggregated_public_key": self.last_state.aggregated_public_key,
            "timestamp": self.last_state.timestamp
        }

    def update_sequencer(self, sequencer_id: str | None) -> None:
        """Update the sequencer configuration."""
        if sequencer_id:
            self.SEQUENCER = self.HISTORICAL_NETWORK_STATE[self.NETWORK_STATUS_TAG].nodes[sequencer_id]

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


zconfig = Config.get_instance(NodeConfig.from_env())
