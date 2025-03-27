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
from schema import NetworkState, NodeSource
from schema import get_node_source
from settings import NodeConfig


class Config:
    _instance = None

    def __init__(self, node_config: NodeConfig):
        self.node_config = node_config
        self.HISTORICAL_NETWORK_STATE: Dict[int, NetworkState] = {}
        self.NODE = {}

        self.APPS = {}
        self.NETWORK_STATUS_TAG = None
        self.ADDRESS = None

        self._SYNCED_FLAG = False

        # Load fields from config
        self.THRESHOLD_PERCENT = node_config.threshold_percent
        self.INIT_SEQUENCER_ID = node_config.init_sequencer_id
        self.SEQUENCER = {'id': self.INIT_SEQUENCER_ID}
        self.API_BATCHES_LIMIT = node_config.api_batches_limit
        self.BANDWIDTH_KB = node_config.bandwidth_kb
        self.PUSH_RATE_LIMIT_WINDOW_SECONDS = node_config.push_rate_limit_window_seconds
        self.MAX_BATCH_SIZE_KB = node_config.max_batch_size_kb

        self.FETCH_APPS_AND_NODES_INTERVAL = node_config.fetch_apps_and_nodes_interval

        self.AGGREGATION_TIMEOUT = node_config.aggregation_timeout
        self.FINALIZATION_TIME_BORDER = node_config.finalization_time_border
        self.SYNC_INTERVAL = node_config.sync_interval
        self.SEND_BATCH_INTERVAL = node_config.send_batch_interval
        self.REMOVE_CHUNK_BORDER = node_config.remove_chunk_border
        self.SNAPSHOT_CHUNK = node_config.snapshot_chunk
        self.SNAPSHOT_CHUNK_SIZE_KB = node_config.snapshot_chunk_size_kb
        self.HOST = node_config.host
        self.PORT = node_config.port
        self.NODE_SOURCE = get_node_source(node_config.nodes_source)
        self.OPERATOR_STATE_RETRIEVER = node_config.operator_state_retriever
        self.REGISTRY_COORDINATOR = node_config.registry_coordinator
        self.RPC_NODE = node_config.rpc_node
        self.SUBGRAPH_URL = node_config.subgraph_url
        self.SNAPSHOT_PATH = node_config.snapshot_path
        self.APPS_FILE = node_config.apps_file
        self.HISTORICAL_NODES_REGISTRY = node_config.historical_nodes_registry
        self.NODES_FILE = node_config.nodes_file
        self.NODES_INFO_SYNC_BORDER = node_config.nodes_info_sync_border
        self.VERSION = node_config.version
        self.BLS_KEY_STORE_PATH = node_config.bls_key_file
        self.ECDSA_KEY_STORE_PATH = node_config.ecdsa_key_file
        self.BLS_KEY_PASSWORD = node_config.bls_key_password
        self.ECDSA_KEY_PASSWORD = node_config.ecdsa_key_password
        self.REGISTER_OPERATOR = node_config.register_operator
        self.REGISTER_SOCKET = node_config.register_socket
        self._MODE = node_config.mode
        self.HEADERS = {"Content-Type": "application/json", "Version": node_config.version}
        # Init node encryption and networks configurations
        self._init_node()

    def get_synced_flag(self):
        return self._SYNCED_FLAG

    def set_synced_flag(self):
        self._SYNCED_FLAG = True

    def unset_synced_flag(self):
        self._SYNCED_FLAG = False

    def get_mode(self):
        return self._MODE

    @staticmethod
    def get_instance(node_config: NodeConfig):
        if not Config._instance:
            Config._instance = Config(node_config=node_config)
        return Config._instance

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(5))
    def get_network_state(self, tag: int) -> NetworkState:
        if tag != 0 and (tag in self.HISTORICAL_NETWORK_STATE):
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

        network_state = NetworkState(tag=tag,
                                     timestamp=int(time.time()),
                                     nodes=nodes_data,
                                     aggregated_public_key=aggregated_public_key,
                                     total_stake=total_stake)

        self.HISTORICAL_NETWORK_STATE[tag] = network_state
        return network_state

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(5))
    def fetch_tag(self):
        if self.NODE_SOURCE == NodeSource.EIGEN_LAYER:
            return utils.fetch_eigen_layer_last_block_number(sub_graph_socket=self.SUBGRAPH_URL)
        elif self.NODE_SOURCE == NodeSource.NODES_REGISTRY:
            return utils.get_nodes_registry_last_tag()
        elif self.NODE_SOURCE == NodeSource.FILE:
            return 0

    def fetch_network_state(self):
        """Fetch the latest network tag and nodes state and update current nodes info and sequencer"""
        # Todo: properly handle exception on fetching tag and corresponding network state
        tag = self.fetch_tag()
        network_state = self.get_network_state(tag=tag)
        self.NETWORK_STATUS_TAG = tag

        nodes_data = network_state.nodes
        if self.ADDRESS in nodes_data:
            # This will be false when node is not registered yet
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
            socket=self.REGISTER_SOCKET,
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

        if urlparse(self.NODE['socket']).port != self.PORT:
            zlogger.warning(
                f"The node port in the .env file does not match the node port provided by {self.NODE_SOURCE.value}.")
            sys.exit()

        self.init_sequencer()

        if self.is_sequencer:
            zlogger.info("This node is acting as the SEQUENCER. ID: %s", self.NODE["id"])

        self.APPS = utils.get_file_content(self.APPS_FILE)

        for app_name in self.APPS:
            snapshot_path = os.path.join(self.SNAPSHOT_PATH, self.VERSION, app_name)
            os.makedirs(snapshot_path, exist_ok=True)

    @property
    def node_send_limit_size(self) -> float:
        return self.BANDWIDTH_KB / len(self.NODES)**2

    @property
    def node_receive_limit_size(self) -> float:
        return self.BANDWIDTH_KB / (len(self.NODES) - 1)

    @property
    def is_sequencer(self):
        return self.SEQUENCER["id"] == self.NODE["id"]

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


zconfig = Config.get_instance(node_config=NodeConfig())
