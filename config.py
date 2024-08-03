"""
Configuration functions for the ZSequencer.
"""

import cProfile
import functools
import json
import os
import sys
import pstats
import requests
from typing import Any

from dotenv import load_dotenv
from eigensdk.crypto.bls import attestation
from web3 import Account
from eigensdk.chainio.clients.builder import BuildAllConfig, build_all

class Config:
    _instance = None

    def __new__(cls) -> "Config":
        if cls._instance is None:
            cls._instance = super(Config, cls).__new__(cls)
            cls._instance.load_environment_variables()
        return cls._instance

    @staticmethod
    def load_json_file(file_path: str) -> dict[str, Any]:
        """Load JSON data from a file."""
        try:
            with open(file=file_path, mode="r", encoding="utf-8") as json_file:
                return json.load(json_file)
        except FileNotFoundError:
            print(f"File not found: {file_path}")
            return {}
        except json.JSONDecodeError:
            print(f"Error decoding JSON from file: {file_path}")
            return {}
    
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
    def fetch_eigenlayer_nodes_data(subgraph_url: str, rpc_node: str, registry_coordinator: str,
                               operator_state_retriever: str) -> dict[str, Any]:
        """Retrieve nodes data from Eigenlayer"""
        query = """
        query MyQuery {
        newPubkeyRegistrations {
            pubkeyG2_X
            pubkeyG2_Y
            pubkeyG1_Y
            pubkeyG1_X
            operator
            blockTimestamp
            blockNumber
        }
        }
        """
        payload = {
            "query": query
        }
        response = requests.post(subgraph_url, json=payload)
        data = response.json()
        registrations = data['data']['newPubkeyRegistrations']
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
        stakes = { operator.operator.lower(): operator.stake for operator in operators }
        for operator in nodes_raw_data:
            nodes_raw_data[operator]['stake'] = stakes[operator]

        nodes: dict[str, dict[str, Any]] = {}
        for node_id, data in nodes_raw_data.items():
            pub_g2 = '1 ' + data['pubkeyG2_X'][0] + ' ' + data['pubkeyG2_X'][1] + ' '\
                            + data['pubkeyG2_Y'][0] + ' ' + data['pubkeyG2_Y'][1]
            nodes[node_id] = {
                'id': node_id,
                'public_key_g2': pub_g2,
                'address': data['operator'],
                'host': '127.0.0.1',
                'port': '6001',
                'stake': float(data['stake'])/(10**18)
            }
        return nodes
        
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
        ]
        eigenlayer_vars: list[str] = [
            "ZSEQUENCER_SUBGRAPH_URL",
            "ZSEQUENCER_RPC_NODE",
            "ZSEQUENCER_REGISTRY_COORDINATOR",
            "ZSEQUENCER_OPERATOR_STATE_RETRIEVER"
        ]

        if not all(os.getenv(var) for var in eigenlayer_vars) and not os.getenv("ZSEQUENCER_NODES_FILE"):
            raise EnvironmentError(
                "Either Eigenlayer node variables or ZSEQUENCER_NODES_FILE must be set to configure Nodes File."
            )
        
        missing_vars: list[str] = [var for var in required_vars if not os.getenv(var)]

        missing_vars
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
        self.NODES_FILE: str = os.getenv("ZSEQUENCER_NODES_FILE", "./nodes.json")
        self.APPS_FILE: str = os.getenv("ZSEQUENCER_APPS_FILE", "./apps.json")
        self.SNAPSHOT_PATH: str = os.getenv("ZSEQUENCER_SNAPSHOT_PATH", "./data/")

        bls_key_store_path: str = os.getenv("ZSEQUENCER_BLS_KEY_FILE", "")
        ecdsa_key_store_path: str = os.getenv("ZSEQUENCER_ECDSA_KEY_FILE", "")

        bls_key_password: str = os.getenv("ZSEQUENCER_BLS_KEY_PASSWORD", "")
        bls_key_pair: attestation.KeyPair = attestation.KeyPair.read_from_file(
            bls_key_store_path, bls_key_password)
        self.bls_public_key: str = bls_key_pair.pub_g2.getStr(10).decode('utf-8')
        bls_private_key: str = bls_key_pair.priv_key.getStr(10).decode('utf-8')
        print(f"BLS Public Key G2: {self.bls_public_key}")
        ecdsa_key_password: str = os.getenv("ZSEQUENCER_ECDSA_KEY_PASSWORD", "")
        with open(ecdsa_key_store_path, 'r') as f:
            encrypted_json: str = json.loads(f.read())
        ecdsa_private_key: str = Account.decrypt(encrypted_json, ecdsa_key_password)
        self.NODE_SOURCE = 'FILE'
        if os.getenv('ZSEQUENCER_SUBGRAPH_URL'):

            self.NODE_SOURCE = 'EIGENLAYER'
            self.SUBGRAPH_URL = os.getenv('ZSEQUENCER_SUBGRAPH_URL')
            self.RPC_NODE = os.getenv('ZSEQUENCER_RPC_NODE')
            self.REGISTRY_COORDINATOR = os.getenv('ZSEQUENCER_REGISTRY_COORDINATOR')
            self.OPERATOR_STATE_RETRIEVER = os.getenv('ZSEQUENCER_OPERATOR_STATE_RETRIEVER')
            self.NODES = Config.fetch_eigenlayer_nodes_data(
                self.SUBGRAPH_URL, self.RPC_NODE, self.REGISTRY_COORDINATOR, self.OPERATOR_STATE_RETRIEVER
            )
        else:
            self.NODES: dict[str, dict[str, Any]] = Config.get_file_content(self.NODES_FILE)
        
        
        self.NODE: dict[str, Any] = {}
        for node in self.NODES.values():
            public_key_g2: str = node["public_key_g2"]
            if public_key_g2 == self.bls_public_key:
                self.NODE = node
            node["public_key_g2"] = attestation.new_zero_g2_point()
            node["public_key_g2"].setStr(public_key_g2.encode("utf-8"))
        if not self.NODE:
            print(
                "A node with this public key not found in nodes.json"
            )
            sys.exit()

        self.NODE["ecdsa_private_key"] = ecdsa_private_key
        self.NODE["bls_key_pair"] = bls_key_pair

        os.makedirs(self.SNAPSHOT_PATH, exist_ok=True)

        self.PORT: int = int(os.getenv("ZSEQUENCER_PORT", "6000"))
        self.SNAPSHOT_CHUNK: int = int(os.getenv("ZSEQUENCER_SNAPSHOT_CHUNK", "1000"))
        self.REMOVE_CHUNK_BORDER: int = int(
            os.getenv("ZSEQUENCER_REMOVE_CHUNK_BORDER", "2")
        )

        self.SEND_TXS_INTERVAL: float = float(
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
        self.THRESHOLD_PERCENT: int = float(
            os.getenv("ZSEQUENCER_THRESHOLD_PERCENT", str(100))
        )

        self.AGGREGATED_PUBLIC_KEY: attestation.G2Point = (
            self.get_aggregated_public_key()
        )
        self.TOTAL_STAKE = sum([node['stake'] for node in self.NODES.values()])

        #self.SEQUENCER: dict[str, Any] = self.NODES["1"]

        self.APPS: dict[str, dict[str, Any]] = self.load_json_file(self.APPS_FILE)

        self.HEADERS: dict[str, Any] = {"Content-Type": "application/json"}

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
