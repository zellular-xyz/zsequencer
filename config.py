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
from threading import Thread
from typing import Any
from urllib.parse import urlparse

from dotenv import load_dotenv
from eigensdk.crypto.bls import attestation
from web3 import Account
from eigensdk.chainio.clients.builder import BuildAllConfig, build_all
from common.logger import zlogger


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
    
    @staticmethod
    def fetch_eigenlayer_nodes_data() -> dict[str, Any]:
        """Retrieve nodes data from Eigenlayer"""
        subgraph_url = os.getenv('ZSEQUENCER_SUBGRAPH_URL')
        rpc_node = os.getenv('ZSEQUENCER_RPC_NODE')
        registry_coordinator = os.getenv('ZSEQUENCER_REGISTRY_COORDINATOR')
        operator_state_retriever = os.getenv('ZSEQUENCER_OPERATOR_STATE_RETRIEVER')

        query = """query MyQuery {
            newPubkeyRegistrations {
                pubkeyG2_X
                pubkeyG2_Y
                pubkeyG1_Y
                pubkeyG1_X
                operator
            }
        }
        """

        response = requests.post(subgraph_url, json={ "query": query })
        data = response.json()
        registrations = data['data']['newPubkeyRegistrations']
        for registration in registrations:
            registration['operator'] = registration['operator'].lower()
        nodes_raw_data = { registration['operator']: registration for registration in registrations }

        config = BuildAllConfig(
            eth_http_url=rpc_node,
            registry_coordinator_addr=registry_coordinator,
            operator_state_retriever_addr=operator_state_retriever,
        )

        clients = build_all(config)
        operators = clients.avs_registry_reader.get_operators_stake_in_quorums_at_current_block(
            quorum_numbers=[0]
        )[0]
        stakes = { operator.operator.lower(): {'stake': operator.stake, 'id':operator.operator_id} for operator in operators }
        
        query = """query MyQuery {
            operatorSocketUpdates {
                socket
                operatorId
                id
            }
        }"""
        response = requests.post(subgraph_url, json={ "query": query })
        data = response.json()
        updates = data['data']['operatorSocketUpdates']
        add_http = lambda socket: f"http://{socket}" if not socket.startswith('http') else socket
        sockets = { update['operatorId']: add_http(update['socket']) for update in updates }
        for operator in nodes_raw_data:
            stake = stakes.get(operator, {}).get('stake', 0)
            nodes_raw_data[operator]['stake'] = stake
            operator_id = stakes.get(operator, {}).get('id', None)
            nodes_raw_data[operator]['socket'] = sockets.get(operator_id, None)

        nodes: dict[str, dict[str, Any]] = {}
        default_nodes_list = {
            '0x747b80a1c0b0e6031b389e3b7eaf9b5f759f34ed',
            '0x3eaa1c283dbf13357257e652649784a4cc08078c',
            '0x906585f83fa7d29b96642aa8f7b4267ab42b7b6c',
            '0x93d89ade53b8fcca53736be1a0d11d342d71118b'
        }
        for node_id, data in nodes_raw_data.items():
            pub_g2 = '1 ' + data['pubkeyG2_X'][1] + ' ' + data['pubkeyG2_X'][0] + ' '\
                            + data['pubkeyG2_Y'][1] + ' ' + data['pubkeyG2_Y'][0]
            nodes[node_id] = {
                'id': node_id,
                'public_key_g2': pub_g2,
                'address': data['operator'],
                'socket': data['socket'],
            }
            
            if node_id not in default_nodes_list:
                nodes[node_id]['stake'] = min(float(data['stake'])/(10**18), 1.0)
            else:
                nodes[node_id]['stake'] = float(data['stake'])/(10**18)
        return nodes
    
        
    def fetch_nodes(self):
        """Fetchs the nodes data."""
        if self.NODE_SOURCE == 'eigenlayer':
            nodes_data = Config.fetch_eigenlayer_nodes_data()
        else:
            nodes_data = Config.get_file_content(self.NODES_FILE)

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
        rpc_node = os.getenv('ZSEQUENCER_RPC_NODE')
        registry_coordinator = os.getenv('ZSEQUENCER_REGISTRY_COORDINATOR')
        operator_state_retriever = os.getenv('ZSEQUENCER_OPERATOR_STATE_RETRIEVER')

        config = BuildAllConfig(
            eth_http_url=rpc_node,
            registry_coordinator_addr=registry_coordinator,
            operator_state_retriever_addr=operator_state_retriever,
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

        if os.getenv("ZSEQUENCER_NODES_SOURCE") == 'eigenlayer':
            required_vars.extend(eigenlayer_vars)
        else:
            required_vars.append("ZSEQUENCER_NODES_FILE")
        
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
        """Load environment variables from a .env file and validate them."""
        if os.path.exists(".env"):
            load_dotenv(dotenv_path=".env", override=False)
        self.validate_env_variables()

        self.VERSION = "v0.0.11"
        self.HEADERS: dict[str, Any] = {
            "Content-Type": "application/json",
            "Version": self.VERSION
        }
        self.NODES_INFO_SYNC_BORDER = 5 # in seconds
        self.IS_SYNCING: bool = True
        self.NODES_FILE: str = os.getenv("ZSEQUENCER_NODES_FILE", "./nodes.json")
        self.APPS_FILE: str = os.getenv("ZSEQUENCER_APPS_FILE", "./apps.json")
        self.SNAPSHOT_PATH: str = os.getenv("ZSEQUENCER_SNAPSHOT_PATH", "./data/")

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

        self.NODE_SOURCE = os.getenv("ZSEQUENCER_NODES_SOURCE")
        if self.NODE_SOURCE == 'eigenlayer':
            self.NODES: dict[str, dict[str, Any]] = Config.fetch_eigenlayer_nodes_data()
        else:
            self.NODES: dict[str, dict[str, Any]] = Config.get_file_content(self.NODES_FILE)
        
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
            if self.NODE_SOURCE != 'eigenlayer':
                data_source = f'{self.NODES_FILE}'
            else:
                data_source = 'Eigenlayer network'
            zlogger.warning(f"The node port in the .env file does not match the node port provided by {data_source}.")
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
        self.FETCH_APPS_AND_NODES_INTERVAL: int = int (
            os.getenv("ZSEQUENCER_FETCH_APPS_AND_NODES_INTERVAL", "60")
        )
        self.API_BATCHES_LIMIT: int = int (
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
