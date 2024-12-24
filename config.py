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
from pprint import pprint
from random import randbytes
from threading import Thread
from typing import List
from urllib.parse import urlparse
from typing import Dict, Any, Optional
from dotenv import load_dotenv
from eigensdk.crypto.bls import attestation
from nodes_snapshot_timeseries_server import NodesSnapshotClient, NodeInfo
from web3 import Account
from eigensdk.chainio.clients.builder import BuildAllConfig, build_all
from common.logger import zlogger


class Config:
    _instance = None

    def __init__(self):
        self.nodes_info_source = None
        self.address = None
        self.apps = None
        self.headers = None
        self.version = None
        self.nodes_info_sync_border = 0
        self.is_syncing = True
        self.nodes_file = None
        self.apps_file = None
        self.snapshot_path = None
        self.send_batch_interval = None
        self.sync_interval = None
        self.finalization_time_border = None
        self.aggregation_timeout = None
        self.fetch_apps_and_nodes_interval = None
        self.api_batches_limit = None
        self.snapshot_chunk = None
        self.remove_chunk_border = None
        self.port = None
        self.historical_snapshot_server_socket = None
        self.nodes_info = {}
        self.nodes_last_data = {}
        self.node_info = {}
        self.total_stake = 0
        self.aggregated_public_key = None
        self.threshold_percent = 0
        self.init_sequencer_id = None
        self.sequencer = {}
        self.subgraph_url = ''
        self.rpc_node = ''
        self.registry_coordinator = ''
        self.operator_state_retriever = ''

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

    def fetch_eigenlayer_nodes_data(self) -> dict[str, Any]:
        """Retrieve nodes data from Eigenlayer"""

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

        response = requests.post(self.subgraph_url, json={"query": query})
        data = response.json()
        registrations = data['data']['newPubkeyRegistrations']
        for registration in registrations:
            registration['operator'] = registration['operator'].lower()
        nodes_raw_data = {registration['operator']: registration for registration in registrations}

        config = BuildAllConfig(
            eth_http_url=self.rpc_node,
            registry_coordinator_addr=self.registry_coordinator,
            operator_state_retriever_addr=self.operator_state_retriever,
        )

        clients = build_all(config)
        operators = clients.avs_registry_reader.get_operators_stake_in_quorums_at_current_block(
            quorum_numbers=[0]
        )[0]
        stakes = {operator.operator.lower(): {'stake': operator.stake, 'id': operator.operator_id} for operator in
                  operators}

        query = """query MyQuery {
            operatorSocketUpdates {
                socket
                operatorId
                id
            }
        }"""
        response = requests.post(self.subgraph_url, json={"query": query})
        data = response.json()
        updates = data['data']['operatorSocketUpdates']
        add_http = lambda socket: f"http://{socket}" if not socket.startswith('http') else socket
        sockets = {update['operatorId']: add_http(update['socket']) for update in updates}
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
            pub_g2 = '1 ' + data['pubkeyG2_X'][1] + ' ' + data['pubkeyG2_X'][0] + ' ' \
                     + data['pubkeyG2_Y'][1] + ' ' + data['pubkeyG2_Y'][0]
            nodes[node_id] = {
                'id': node_id,
                'public_key_g2': pub_g2,
                'address': data['operator'],
                'socket': data['socket'],
            }

            if node_id not in default_nodes_list:
                nodes[node_id]['stake'] = min(float(data['stake']) / (10 ** 18), 1.0)
            else:
                nodes[node_id]['stake'] = float(data['stake']) / (10 ** 18)
        return nodes

    def get_last_nodes_info(self):
        nodes_data = {}
        if self.nodes_info_source == 'eigenlayer':
            nodes_data = self.fetch_eigenlayer_nodes_data()
        elif self.nodes_info_source == 'file':
            nodes_data = self.get_file_content(self.nodes_file)
        elif self.nodes_info_source == 'historical_snapshot_server':
            nodes_data = self.get_historical_snapshot_server_network_info()
        return nodes_data

    def fetch_nodes(self):
        """Fetchs the nodes data."""
        nodes_data = self.get_last_nodes_info()
        for node_data in nodes_data.values():
            public_key_g2: str = node_data["public_key_g2"]
            node_data["public_key_g2"] = attestation.new_zero_g2_point()
            node_data["public_key_g2"].setStr(public_key_g2.encode("utf-8"))

        update_last_nodes_data = len(nodes_data) != len(self.nodes_info) or any(
            nodes_data[node_id]["stake"] != self.nodes_info[node_id]["stake"]
            for node_id in self.nodes_info
        )
        if update_last_nodes_data:
            self.nodes_last_data.update({
                "total_stake": self.total_stake,
                "aggregated_public_key": self.aggregated_public_key,
                "timestamp": int(time.time())
            })
        self.node_info.update(nodes_data[self.address])
        self.nodes_info.update(nodes_data)
        self.sequencer.update(self.nodes_info[self.sequencer['id']])
        self.total_stake = sum([node['stake'] for node in self.nodes_info.values()])
        self.aggregated_public_key = self.get_aggregated_public_key()

    def register_operator(self, ecdsa_private_key, bls_key_pair) -> None:

        config = BuildAllConfig(
            eth_http_url=self.rpc_node,
            registry_coordinator_addr=self.registry_coordinator,
            operator_state_retriever_addr=self.operator_state_retriever,
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

    @property
    def node_info(self) -> NodeInfo:
        return NodeInfo(

        )


    def init_sequencer(self) -> None:
        """Finds the initial sequencer id."""
        sequencers_stake: dict[str, Any] = {
            node_id: 0 for node_id in list(self.nodes_info.keys())
        }
        for node_id in list(self.nodes_info.keys()):
            if node_id == self.node_info["id"]:
                continue
            url: str = f"{self.nodes_info[node_id]['socket']}/node/state"
            try:
                response = requests.get(url=url, headers=self.headers, timeout=1).json()
                if response["data"]["version"] != self.version:
                    continue
                sequencer_id = response["data"]["sequencer_id"]
                sequencers_stake[sequencer_id] += self.nodes_info[node_id]["stake"]
            except Exception:
                zlogger.warning(f"Unable to get state from {node_id}")
        max_stake_id = max(sequencers_stake, key=lambda k: sequencers_stake[k])
        sequencers_stake[max_stake_id] += self.node_info["stake"]
        if 100 * sequencers_stake[max_stake_id] / self.total_stake >= self.threshold_percent and \
                sequencers_stake[max_stake_id] > self.node_info["stake"]:
            self.update_sequencer(max_stake_id)
        else:
            self.update_sequencer(self.init_sequencer_id)

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
        eigenlayer_vars: List[str] = [
            "ZSEQUENCER_SUBGRAPH_URL",
            "ZSEQUENCER_RPC_NODE",
            "ZSEQUENCER_REGISTRY_COORDINATOR",
            "ZSEQUENCER_OPERATOR_STATE_RETRIEVER"
        ]

        nodes_source = os.getenv("ZSEQUENCER_NODES_SOURCE")
        if nodes_source == 'eigenlayer':
            required_vars.extend(eigenlayer_vars)
        elif nodes_source == 'file':
            required_vars.append("ZSEQUENCER_NODES_FILE")
        elif nodes_source == 'historical_snapshot_server':
            required_vars.append("ZSEQUENCER_HISTORICAL_SNAPSHOT_SERVER_SOCKET")

        missing_vars: list[str] = [var for var in required_vars if not os.getenv(var)]
        if missing_vars:
            raise EnvironmentError(
                f"Missing environment variables: {', '.join(missing_vars)}"
            )

    def get_aggregated_public_key(self) -> attestation.G2Point:
        aggregated_public_key: attestation.G2Point = attestation.new_zero_g2_point()
        for node in self.nodes_info.values():
            aggregated_public_key = aggregated_public_key + node["public_key_g2"]
        return aggregated_public_key

    @staticmethod
    def compute_agg_public_key(nodes_info):
        aggregated_public_key: attestation.G2Point = attestation.new_zero_g2_point()
        for node in nodes_info.values():
            aggregated_public_key = aggregated_public_key + node["public_key_g2"]
        return aggregated_public_key

    def load_environment_variables(self):
        """Load environment variables from a .env file and validate them."""
        # if os.path.exists(".env"):
        #     load_dotenv(dotenv_path=".env", override=False)
        self.validate_env_variables()

        self.version = "v0.0.12"
        self.headers: dict[str, Any] = {
            "Content-Type": "application/json",
            "Version": self.version
        }
        self.nodes_info_sync_border = 5  # in seconds
        self.is_syncing: bool = True
        self.nodes_file: str = os.getenv("ZSEQUENCER_NODES_FILE", "./nodes.json")
        self.apps_file: str = os.getenv("ZSEQUENCER_APPS_FILE", "./apps.json")
        self.snapshot_path: str = os.getenv("ZSEQUENCER_SNAPSHOT_PATH", "./data/")
        self.historical_snapshot_server_socket = os.getenv("ZSEQUENCER_HISTORICAL_SNAPSHOT_SERVER_SOCKET",
                                                           "localhost:8000")

        self.subgraph_url = os.getenv('ZSEQUENCER_SUBGRAPH_URL', '')
        self.rpc_node = os.getenv('ZSEQUENCER_RPC_NODE', '')
        self.registry_coordinator = os.getenv('ZSEQUENCER_REGISTRY_COORDINATOR', '')
        self.operator_state_retriever = os.getenv('ZSEQUENCER_OPERATOR_STATE_RETRIEVER', '')

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
        self.address = Account.from_key(ecdsa_private_key).address.lower()

        self.nodes_info_source = os.getenv("ZSEQUENCER_NODES_SOURCE")
        self.nodes_info = self.get_last_nodes_info()

        self.node_info: dict[str, Any] = {}
        for node in self.nodes_info.values():
            public_key_g2: str = node["public_key_g2"]
            node["public_key_g2"] = attestation.new_zero_g2_point()
            node["public_key_g2"].setStr(public_key_g2.encode("utf-8"))

        if self.address in self.nodes_info:
            self.node_info = self.nodes_info[self.address]
            public_key_g2: str = self.node_info["public_key_g2"].getStr(10).decode('utf-8')
            public_key_g2_from_private: str = bls_key_pair.pub_g2.getStr(10).decode('utf-8')
            error_msg: str = "the bls key pair public key does not match public of the node in the nodes list"
            assert public_key_g2 == public_key_g2_from_private, error_msg
        else:
            if os.getenv("ZSEQUENCER_REGISTER_OPERATOR") == 'true':
                self.register_operator(ecdsa_private_key, bls_key_pair)
                zlogger.warning("Operator registration transaction sent.")
            zlogger.warning("Operator not found in the nodes' list")
            sys.exit()

        self.node_info["ecdsa_private_key"] = ecdsa_private_key
        self.node_info["bls_key_pair"] = bls_key_pair

        os.makedirs(self.snapshot_path, exist_ok=True)

        self.port: int = int(os.getenv("ZSEQUENCER_PORT", "6000"))
        if self.port != urlparse(self.node_info['socket']).port:
            if self.nodes_info_source == 'eigenlayer':
                data_source = 'Eigenlayer network'
            else:
                data_source = self.nodes_file

            zlogger.warning(f"The node port in the .env file does not match the node port provided by {data_source}.")
            sys.exit()

        self.snapshot_chunk: int = int(os.getenv("ZSEQUENCER_SNAPSHOT_CHUNK", "1000"))
        self.remove_chunk_border: int = int(os.getenv("ZSEQUENCER_REMOVE_CHUNK_BORDER", "2"))

        self.send_batch_interval: float = float(os.getenv("ZSEQUENCER_SEND_TXS_INTERVAL", "5"))
        self.sync_interval: float = float(os.getenv("ZSEQUENCER_SYNC_INTERVAL", "30"))
        self.finalization_time_border: int = int(os.getenv("ZSEQUENCER_FINALIZATION_TIME_BORDER", "120"))
        self.aggregation_timeout: int = int(os.getenv("ZSEQUENCER_SIGNATURES_AGGREGATION_TIMEOUT", "5"))
        self.fetch_apps_and_nodes_interval: int = int(os.getenv("ZSEQUENCER_FETCH_APPS_AND_NODES_INTERVAL", "60"))
        self.api_batches_limit: int = int(os.getenv("ZSEQUENCER_API_BATCHES_LIMIT", "100"))
        self.init_sequencer_id: str = os.getenv("ZSEQUENCER_INIT_SEQUENCER_ID")
        self.threshold_percent: int = float(os.getenv("ZSEQUENCER_THRESHOLD_PERCENT", str(100)))

        self.aggregated_public_key: attestation.G2Point = (self.get_aggregated_public_key())
        self.total_stake = sum([node['stake'] for node in self.nodes_info.values()])

        self.init_sequencer()

        if self.sequencer["id"] == self.node_info["id"]:
            self.is_syncing = False

        self.apps: dict[str, dict[str, Any]] = Config.get_file_content(self.apps_file)

        for app_name in self.apps:
            snapshot_path: str = os.path.join(
                self.snapshot_path, self.version, app_name
            )
            os.makedirs(snapshot_path, exist_ok=True)

        self.nodes_last_data = {
            "total_stake": self.total_stake,
            "aggregated_public_key": self.aggregated_public_key,
            "timestamp": int(time.time())
        }

        if self.nodes_info_source == 'historical_snapshot_server':
            self.register_node_info()

    def update_sequencer(self, sequencer_id: str | None) -> None:
        """Update the sequencer configuration."""
        if sequencer_id:
            self.sequencer = self.nodes_info[sequencer_id]

    def get_network_info(self, signature_tag: int):
        if self.nodes_info_source == 'eigenlayer':
            return self.get_eigen_network_info(signature_tag=signature_tag)
        elif self.nodes_info_source == 'historical_snapshot_server':
            return self.get_historical_snapshot_server_network_info(timestamp=signature_tag)
        elif self.nodes_info_source == 'file':
            return self.get_last_nodes_info()

    def get_historical_snapshot_server_network_info(self, timestamp: Optional[int]):
        client = NodesSnapshotClient(socket=self.historical_snapshot_server_socket)
        return client.get_network_snapshot(timestamp=timestamp)

    def get_eigen_network_info(self, signature_tag: int):

        graphql_query = {
            "query": f"""
    {{
        operators(block: {{ number: {signature_tag} }}) {{
            id
            socket
            stake
            pubkeyG2_X
            pubkeyG2_Y
        }}
    }}
    """
        }

        response = requests.post(self.subgraph_url,
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


zconfig: Config = Config()
