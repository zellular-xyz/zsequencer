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
from random import randbytes
from enum import Enum
from historical_nodes_registry import NodesRegistryClient
from threading import Thread
from typing import Any, List, Dict, Optional
from urllib.parse import urlparse

import validators
from dotenv import load_dotenv
from eigensdk.crypto.bls import attestation
from web3 import Account
from eigensdk.chainio.clients.builder import BuildAllConfig, build_all
from common.logger import zlogger


class NodeSource(Enum):
    FILE = "file"
    EIGEN_LAYER = "eigenlayer"
    NODES_REGISTRY = "historical_nodes_registry"


def get_node_source(value: str) -> NodeSource | None:
    try:
        return NodeSource(value)
    except ValueError:
        return None


class Config:
    _instance = None

    def __new__(cls) -> "Config":
        if cls._instance is None:
            cls._instance = super(Config, cls).__new__(cls)
            cls._instance.load_environment_variables()
        return cls._instance

    @staticmethod
    def get_file_content(source: str) -> str:
        """Get the json contents of a file"""
        if source.startswith('http://') or source.startswith('https://'):
            response = requests.get(source)
            response.raise_for_status()
            return response.json()
        elif os.path.isfile(source):
            with open(source, 'r', encoding='utf-8') as file:
                content = json.loads(file.read())
            return content
        else:
            raise ValueError("The source provided is neither a valid URL nor a valid file path.")

    def fetch_historical_nodes_registry_data(self, timestamp: Optional[int]) -> Dict[str, Any]:
        snapshot = NodesRegistryClient(self.HISTORICAL_NODES_REGISTRY).get_network_snapshot(timestamp=timestamp)
        snapshot_data = {address: node_info.dict() for address, node_info in snapshot.items()}
        return snapshot_data

    def fetch_nodes_info(self) -> Dict[str, Dict[str, Any]]:
        nodes_data: Dict[str, Dict[str, Any]] = {}
        if self.NODE_SOURCE == NodeSource.FILE:
            nodes_data = self.get_file_content(self.NODES_FILE)
        elif self.NODE_SOURCE == NodeSource.EIGEN_LAYER:
            nodes_data = self.get_eigen_network_info(block_number=self.NETWORK_STATUS_TAG)
        elif self.NODE_SOURCE == NodeSource.NODES_REGISTRY:
            nodes_data = self.fetch_historical_nodes_registry_data(timestamp=self.NETWORK_STATUS_TAG)

        return nodes_data

    def _fetch_eigen_layer_last_block_number(self) -> int:
        response = requests.post(self.SUBGRAPH_URL,
                                 headers={"content-type": "application/json"},
                                 json={"query": "{ _meta { block { number } } }"})

        if response.status_code == 200:
            block_number = int(response.json()["data"]["_meta"]["block"]["number"])
            return block_number

    def fetch_network_state_last_tag(self):
        if self.NODE_SOURCE == NodeSource.EIGEN_LAYER:
            self.NETWORK_STATUS_TAG = self._fetch_eigen_layer_last_block_number()
        elif self.NODE_SOURCE == NodeSource.NODES_REGISTRY:
            self.NETWORK_STATUS_TAG = int(time.time())
        elif self.NODE_SOURCE == NodeSource.FILE:
            self.NETWORK_STATUS_TAG = 0

    def fetch_nodes(self):
        """Fetchs the nodes data."""
        nodes_data = self.fetch_nodes_info()

        for node_data in nodes_data.values():
            public_key_g2: str = node_data["public_key_g2"]
            node_data["public_key_g2"] = attestation.new_zero_g2_point()
            node_data["public_key_g2"].setStr(public_key_g2.encode("utf-8"))

        update_last_nodes_data = len(nodes_data) != len(self.NODES) or any(
            nodes_data[node_id]["stake"] != self.NODES[node_id]["stake"]
            for node_id in self.NODES
        )
        if update_last_nodes_data:
            self.NODES_LAST_DATA.update({
                "total_stake": self.TOTAL_STAKE,
                "aggregated_public_key": self.AGGREGATED_PUBLIC_KEY,
                "timestamp": int(time.time())
            })
        self.NODE.update(nodes_data[self.ADDRESS])
        self.NODES.update(nodes_data)
        self.SEQUENCER.update(self.NODES[self.SEQUENCER['id']])
        self.TOTAL_STAKE = sum([node['stake'] for node in self.NODES.values()])
        self.AGGREGATED_PUBLIC_KEY = self.get_aggregated_public_key()

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

    @staticmethod
    def validate_env_variables() -> None:
        """Validate that all required environment variables are set."""
        required_vars: list[str] = [
            "ZSEQUENCER_BLS_KEY_FILE",
            "ZSEQUENCER_BLS_KEY_PASSWORD",
            "ZSEQUENCER_ECDSA_KEY_FILE",
            "ZSEQUENCER_ECDSA_KEY_PASSWORD",
            "ZSEQUENCER_APPS_FILE",
            "ZSEQUENCER_SNAPSHOT_PATH",
            "ZSEQUENCER_PORT",
            "ZSEQUENCER_SNAPSHOT_CHUNK",
            "ZSEQUENCER_REMOVE_CHUNK_BORDER",
            "ZSEQUENCER_THRESHOLD_PERCENT",
            "ZSEQUENCER_SEND_TXS_INTERVAL",
            "ZSEQUENCER_SYNC_INTERVAL",
            "ZSEQUENCER_FINALIZATION_TIME_BORDER",
            "ZSEQUENCER_SIGNATURES_AGGREGATION_TIMEOUT",
            "ZSEQUENCER_FETCH_APPS_AND_NODES_INTERVAL",
            "ZSEQUENCER_INIT_SEQUENCER_ID",
            "ZSEQUENCER_NODES_SOURCE"
        ]
        eigenlayer_vars: list[str] = [
            "ZSEQUENCER_SUBGRAPH_URL",
            "ZSEQUENCER_RPC_NODE",
            "ZSEQUENCER_REGISTRY_COORDINATOR",
            "ZSEQUENCER_OPERATOR_STATE_RETRIEVER"
        ]
        historical_nodes_snapshot_server_vars: List[str] = [
            "ZSEQUENCER_HISTORICAL_NODES_REGISTRY"
        ]
        nodes_source = os.getenv("ZSEQUENCER_NODES_SOURCE")

        if nodes_source == 'eigenlayer':
            required_vars.extend(eigenlayer_vars)
        elif nodes_source == 'file':
            required_vars.append("ZSEQUENCER_NODES_FILE")
        elif nodes_source == 'historical_nodes_registry':
            required_vars.extend(historical_nodes_snapshot_server_vars)

        missing_vars: list[str] = [var for var in required_vars if not os.getenv(var)]
        if missing_vars:
            raise EnvironmentError(
                f"Missing environment variables: {', '.join(missing_vars)}"
            )

    def get_aggregated_public_key(self) -> attestation.G2Point:
        aggregated_public_key: attestation.G2Point = attestation.new_zero_g2_point()
        for node in self.NODES.values():
            aggregated_public_key = aggregated_public_key + node["public_key_g2"]
        return aggregated_public_key

    def load_environment_variables(self):
        self.validate_env_variables()

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

        bls_key_store_path: str = os.getenv("ZSEQUENCER_BLS_KEY_FILE", "")
        ecdsa_key_store_path: str = os.getenv("ZSEQUENCER_ECDSA_KEY_FILE", "")

        bls_key_password: str = os.getenv("ZSEQUENCER_BLS_KEY_PASSWORD", "")
        bls_key_pair: attestation.KeyPair = attestation.KeyPair.read_from_file(
            bls_key_store_path, bls_key_password)
        bls_private_key: str = bls_key_pair.priv_key.getStr(10).decode('utf-8')

        ecdsa_key_password: str = os.getenv("ZSEQUENCER_ECDSA_KEY_PASSWORD", "")
        with open(ecdsa_key_store_path, 'r') as f:
            encrypted_json: str = json.loads(f.read())
        ecdsa_private_key: str = Account.decrypt(encrypted_json, ecdsa_key_password)
        self.ADDRESS = Account.from_key(ecdsa_private_key).address.lower()

        self.NODE_SOURCE = get_node_source(os.getenv("ZSEQUENCER_NODES_SOURCE"))
        self.NETWORK_STATUS_TAG = 0
        self.fetch_network_state_last_tag()
        self.NODES = self.fetch_nodes_info()

        self.NODE: dict[str, Any] = {}
        for node in self.NODES.values():
            public_key_g2: str = node["public_key_g2"]
            node["public_key_g2"] = attestation.new_zero_g2_point()
            node["public_key_g2"].setStr(public_key_g2.encode("utf-8"))

        if self.ADDRESS in self.NODES:
            self.NODE = self.NODES[self.ADDRESS]
            public_key_g2: str = self.NODE["public_key_g2"].getStr(10).decode('utf-8')
            public_key_g2_from_private: str = bls_key_pair.pub_g2.getStr(10).decode('utf-8')
            error_msg: str = "the bls key pair public key does not match public of the node in the nodes list"
            assert public_key_g2 == public_key_g2_from_private, error_msg
        else:
            if os.getenv("ZSEQUENCER_REGISTER_OPERATOR") == 'true':
                self.register_operator(ecdsa_private_key, bls_key_pair)
                zlogger.warning("Operator registration transaction sent.")
            zlogger.warning("Operator not found in the nodes' list")
            sys.exit()

        self.NODE["ecdsa_private_key"] = ecdsa_private_key
        self.NODE["bls_key_pair"] = bls_key_pair

        os.makedirs(self.SNAPSHOT_PATH, exist_ok=True)

        self.PORT: int = int(os.getenv("ZSEQUENCER_PORT", "6000"))
        if self.PORT != urlparse(self.NODE['socket']).port:
            zlogger.warning(
                f"The node port in the .env file does not match the node port provided by {self.NODE_SOURCE.value}.")
            sys.exit()
        self.SNAPSHOT_CHUNK: int = int(os.getenv("ZSEQUENCER_SNAPSHOT_CHUNK", "1000"))
        self.REMOVE_CHUNK_BORDER: int = int(
            os.getenv("ZSEQUENCER_REMOVE_CHUNK_BORDER", "2")
        )

        self.SEND_BATCH_INTERVAL: float = float(
            os.getenv("ZSEQUENCER_SEND_TXS_INTERVAL", "5")
        )
        self.SYNC_INTERVAL: float = float(os.getenv("ZSEQUENCER_SYNC_INTERVAL", "30"))
        self.FINALIZATION_TIME_BORDER: int = int(
            os.getenv("ZSEQUENCER_FINALIZATION_TIME_BORDER", "120")
        )
        self.AGGREGATION_TIMEOUT: int = int(
            os.getenv("ZSEQUENCER_SIGNATURES_AGGREGATION_TIMEOUT", "5")
        )
        self.FETCH_APPS_AND_NODES_INTERVAL: int = int(
            os.getenv("ZSEQUENCER_FETCH_APPS_AND_NODES_INTERVAL", "60")
        )
        self.API_BATCHES_LIMIT: int = int(
            os.getenv("ZSEQUENCER_API_BATCHES_LIMIT", "100")
        )
        self.INIT_SEQUENCER_ID: str = os.getenv(
            "ZSEQUENCER_INIT_SEQUENCER_ID"
        )
        self.THRESHOLD_PERCENT: int = float(
            os.getenv("ZSEQUENCER_THRESHOLD_PERCENT", str(100))
        )

        self.AGGREGATED_PUBLIC_KEY: attestation.G2Point = (
            self.get_aggregated_public_key()
        )
        self.TOTAL_STAKE = sum([node['stake'] for node in self.NODES.values()])

        self.init_sequencer()

        if self.SEQUENCER["id"] == self.NODE["id"]:
            self.IS_SYNCING = False

        self.APPS: dict[str, dict[str, Any]] = Config.get_file_content(self.APPS_FILE)

        for app_name in self.APPS:
            snapshot_path: str = os.path.join(
                self.SNAPSHOT_PATH, self.VERSION, app_name
            )
            os.makedirs(snapshot_path, exist_ok=True)

        self.NODES_LAST_DATA = {
            "total_stake": self.TOTAL_STAKE,
            "aggregated_public_key": self.AGGREGATED_PUBLIC_KEY,
            "timestamp": int(time.time())
        }

    def update_sequencer(self, sequencer_id: str | None) -> None:
        """Update the sequencer configuration."""
        if sequencer_id:
            self.SEQUENCER = self.NODES[sequencer_id]

    def get_eigen_network_info(self, block_number: int):

        graphql_query = {
            "query": f"""
    {{
        operators(block: {{ number: {block_number} }}) {{
            id
            socket
            stake
            pubkeyG2_X
            pubkeyG2_Y
        }}
    }}
    """
        }

        response = requests.post(self.SUBGRAPH_URL,
                                 headers={"content-type": "application/json"},
                                 json=graphql_query)
        result = response.json()
        return {
            item.get("id"): {
                "id": item.get("id"),
                "address": item.get("id"),
                "socket": item.get("socket"),
                "stake": int(item.get("socket")),
                "public_key_g2": '1 ' + item['pubkeyG2_X'][1] + ' ' + item['pubkeyG2_X'][0] + ' ' \
                                 + item['pubkeyG2_Y'][1] + ' ' + item['pubkeyG2_Y'][0]
            }
            for item in result.get("data").get("operators", [])
        }

    def get_network_info(self, tag: int):
        if self.NODE_SOURCE == NodeSource.EIGEN_LAYER:
            return self.get_eigen_network_info(block_number=tag)
        elif self.NODE_SOURCE == NodeSource.NODES_REGISTRY:
            return self.fetch_historical_nodes_registry_data(timestamp=tag)
        elif self.NODE_SOURCE == NodeSource.FILE:
            return self.get_file_content(self.NODES_FILE)

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
