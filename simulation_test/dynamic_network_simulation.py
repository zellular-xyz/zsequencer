"""This script sets up and runs a simple app network for testing."""
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import copy
import json
import time
import secrets
import threading
import socket
import shutil
import random
import requests
from pathlib import Path
from typing import Dict, Tuple, List
from functools import reduce
from pydantic import BaseModel, Field
from historical_nodes_registry import (NodesRegistryClient,
                                       NodeInfo,
                                       SnapShotType,
                                       run_registry_server)
from terminal_exeuction import run_command_on_terminal
from eigensdk.crypto.bls import attestation
from web3 import Account
from requests.exceptions import RequestException


class SimulationConfig(BaseModel):
    NUM_INSTANCES: int = Field(3, description="Number of instances")
    HOST: str = Field("http://127.0.0.1", description="Host address")
    BASE_PORT: int = Field(6000, description="Base port number")
    THRESHOLD_PERCENT: int = Field(67, description="Threshold percentage")
    DST_DIR: str = Field("/tmp/zellular_dev_net", description="Destination directory")
    APPS_FILE: str = Field("/tmp/zellular_dev_net/apps.json", description="Path to the apps file")
    HISTORICAL_NODES_REGISTRY_HOST: str = Field("localhost", description="Historical nodes registry host")
    HISTORICAL_NODES_REGISTRY_PORT: int = Field(8000, description="Historical nodes registry port")
    HISTORICAL_NODES_REGISTRY_SOCKET: str = Field(
        None,
        description="Socket for historical nodes registry",
    )
    ZSEQUENCER_SNAPSHOT_CHUNK: int = Field(1000, description="Snapshot chunk size for ZSequencer")
    ZSEQUENCER_REMOVE_CHUNK_BORDER: int = Field(3, description="Chunk border for ZSequencer removal")
    ZSEQUENCER_SEND_TXS_INTERVAL: float = Field(0.05, description="Interval for sending transactions in ZSequencer")
    ZSEQUENCER_SYNC_INTERVAL: float = Field(0.05, description="Sync interval for ZSequencer")
    ZSEQUENCER_FINALIZATION_TIME_BORDER: int = Field(10, description="Finalization time border for ZSequencer")
    ZSEQUENCER_SIGNATURES_AGGREGATION_TIMEOUT: int = Field(5, description="Timeout for signatures aggregation")
    ZSEQUENCER_FETCH_APPS_AND_NODES_INTERVAL: int = Field(30, description="Interval to fetch apps and nodes")
    ZSEQUENCER_API_BATCHES_LIMIT: int = Field(100, description="API batches limit for ZSequencer")
    ZSEQUENCER_NODES_SOURCES: List[str] = Field(
        ["file", "historical_nodes_registry", "eigenlayer"],
        description="Sources for nodes in ZSequencer",
    )
    APP_NAME: str = Field("simple_app", description="Name of the application")
    BASE_DIRECTORY: str = Field("./examples", description="Base directory path")
    TIMESERIES_NODES_COUNT: List[int] = Field([3, 4, 5, 6, 7, 8, 10, 11, 12, 13],
                                              description="count of nodes available on network at different states")

    class Config:
        validate_assignment = True

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.HISTORICAL_NODES_REGISTRY_SOCKET = (
            f"{self.HISTORICAL_NODES_REGISTRY_HOST}:{self.HISTORICAL_NODES_REGISTRY_PORT}"
        )


class DynamicNetworkSimulation:
    PROJECTS_VIRTUAL_ENV = 'venv/bin/activate'
    PROJECTS_ROOT_DIR = str(Path(__file__).parent.parent)

    def __init__(self, simulation_config: SimulationConfig):
        self.simulation_config = simulation_config
        self.nodes_registry_thread = None
        self.network_transition_thread = None
        self.send_batches_thread = None
        self.sequencer_address = None
        self.network_nodes_state = None
        self.shutdown_event = threading.Event()
        self.nodes_registry_client = NodesRegistryClient(socket=self.simulation_config.HISTORICAL_NODES_REGISTRY_SOCKET)

    @staticmethod
    def delete_directory_contents(directory):
        if not os.path.exists(directory):
            raise FileNotFoundError(f"Directory '{directory}' does not exist.")

        for filename in os.listdir(directory):
            file_path = os.path.join(directory, filename)
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
            except Exception as e:
                print(f"Error deleting {file_path}: {e}")

    @staticmethod
    def generate_keys() -> Dict:
        bls_private_key: str = secrets.token_hex(32)
        bls_key_pair: attestation.KeyPair = attestation.new_key_pair_from_string(bls_private_key)
        ecdsa_private_key: str = secrets.token_hex(32)

        return dict(bls_private_key=bls_private_key,
                    bls_key_pair=bls_key_pair,
                    ecdsa_private_key=ecdsa_private_key)

    @classmethod
    def generate_node_execution_command(cls, node_idx: int) -> str:
        """Run a command in a new terminal tab."""
        script_dir: str = os.path.dirname(os.path.abspath(__file__))
        parent_dir: str = os.path.dirname(script_dir)
        os.chdir(parent_dir)

        virtual_env_path = os.path.join(cls.PROJECTS_ROOT_DIR, cls.PROJECTS_VIRTUAL_ENV)
        node_runner_path = os.path.join(cls.PROJECTS_ROOT_DIR, 'run.py')

        return f"source {virtual_env_path}; python -u {node_runner_path} {str(node_idx)}; echo; read -p 'Press enter to exit...'"

    @staticmethod
    def launch_node(cmd, env_variables):
        run_command_on_terminal(cmd, env_variables)

    def get_timeseries_last_node_idx(self):
        timeseries_nodes_count = self.simulation_config.TIMESERIES_NODES_COUNT

        return reduce(lambda acc,
                             i: acc + [acc[-1] + (timeseries_nodes_count[i] - timeseries_nodes_count[i - 1])
                                       if timeseries_nodes_count[i - 1] < timeseries_nodes_count[i]
                                       else acc[-1]], range(1, len(timeseries_nodes_count)),
                      [timeseries_nodes_count[0] - 1])

    def generate_node_info(self, node_idx: int, keys: Dict) -> NodeInfo:
        bls_private_key, bls_key_pair, ecdsa_private_key = (keys.get('bls_private_key'),
                                                            keys.get('bls_key_pair'),
                                                            keys.get('ecdsa_private_key'))
        address = Account().from_key(ecdsa_private_key).address.lower()

        return NodeInfo(id=address,
                        public_key_g2=bls_key_pair.pub_g2.getStr(10).decode("utf-8"),
                        address=address,
                        socket=f"{self.simulation_config.HOST}:{str(self.simulation_config.BASE_PORT + node_idx)}",
                        stake=10)

    def prepare_node(self,
                     node_idx: int,
                     keys: Dict,
                     sequencer_initial_address: str) -> Tuple[str, Dict]:
        bls_private_key, bls_key_pair, ecdsa_private_key = (keys.get('bls_private_key'),
                                                            keys.get('bls_key_pair'),
                                                            keys.get('ecdsa_private_key'))

        DST_DIR = self.simulation_config.DST_DIR
        data_dir: str = f"{DST_DIR}/db_{node_idx}"
        if os.path.exists(data_dir):
            shutil.rmtree(data_dir)

        bls_key_file: str = f"{DST_DIR}/bls_key{node_idx}.json"
        bls_passwd: str = f'a{node_idx}'
        bls_key_pair: attestation.KeyPair = attestation.new_key_pair_from_string(bls_private_key)
        bls_key_pair.save_to_file(bls_key_file, bls_passwd)

        ecdsa_key_file: str = f"{DST_DIR}/ecdsa_key{node_idx}.json"
        ecdsa_passwd: str = f'b{node_idx}'
        encrypted_json = Account.encrypt(ecdsa_private_key, ecdsa_passwd)
        with open(ecdsa_key_file, 'w') as f:
            f.write(json.dumps(encrypted_json))

        env_variables = {
            "ZSEQUENCER_BLS_KEY_FILE": bls_key_file,
            "ZSEQUENCER_BLS_KEY_PASSWORD": bls_passwd,
            "ZSEQUENCER_ECDSA_KEY_FILE": ecdsa_key_file,
            "ZSEQUENCER_ECDSA_KEY_PASSWORD": ecdsa_passwd,
            "ZSEQUENCER_APPS_FILE": self.simulation_config.APPS_FILE,
            "ZSEQUENCER_SNAPSHOT_PATH": data_dir,
            "ZSEQUENCER_HISTORICAL_NODES_REGISTRY": self.simulation_config.HISTORICAL_NODES_REGISTRY_SOCKET,
            "ZSEQUENCER_PORT": str(self.simulation_config.BASE_PORT + node_idx),
            "ZSEQUENCER_SNAPSHOT_CHUNK": str(self.simulation_config.ZSEQUENCER_SNAPSHOT_CHUNK),
            "ZSEQUENCER_REMOVE_CHUNK_BORDER": str(self.simulation_config.ZSEQUENCER_REMOVE_CHUNK_BORDER),
            "ZSEQUENCER_THRESHOLD_PERCENT": str(self.simulation_config.THRESHOLD_PERCENT),
            "ZSEQUENCER_SEND_TXS_INTERVAL": str(self.simulation_config.ZSEQUENCER_SEND_TXS_INTERVAL),
            "ZSEQUENCER_SYNC_INTERVAL": str(self.simulation_config.ZSEQUENCER_SYNC_INTERVAL),
            "ZSEQUENCER_FINALIZATION_TIME_BORDER": str(self.simulation_config.ZSEQUENCER_FINALIZATION_TIME_BORDER),
            "ZSEQUENCER_SIGNATURES_AGGREGATION_TIMEOUT": str(
                self.simulation_config.ZSEQUENCER_SIGNATURES_AGGREGATION_TIMEOUT),
            "ZSEQUENCER_FETCH_APPS_AND_NODES_INTERVAL": str(
                self.simulation_config.ZSEQUENCER_FETCH_APPS_AND_NODES_INTERVAL),
            "ZSEQUENCER_API_BATCHES_LIMIT": str(self.simulation_config.ZSEQUENCER_API_BATCHES_LIMIT),
            "ZSEQUENCER_INIT_SEQUENCER_ID": sequencer_initial_address,
            "ZSEQUENCER_NODES_SOURCE": self.simulation_config.ZSEQUENCER_NODES_SOURCES[1],
            "ZSEQUENCER_REGISTER_OPERATOR": "false",
            "ZSEQUENCER_VERSION": "v0.0.12",
            "ZSEQUENCER_NODES_FILE": ""}

        return self.generate_node_execution_command(node_idx), env_variables

    def wait_nodes_registry_server(self, timeout: float = 20.0, interval: float = 0.5):
        start_time = time.time()
        host, port = self.simulation_config.HISTORICAL_NODES_REGISTRY_HOST, self.simulation_config.HISTORICAL_NODES_REGISTRY_PORT

        while time.time() - start_time < timeout:
            try:
                with socket.create_connection((host, port), timeout=interval):
                    print(f"Server is up and running on {host}:{port}")
                    return
            except (socket.timeout, ConnectionRefusedError):
                print(f"Waiting for server at {host}:{port}...")
                time.sleep(interval)
        raise TimeoutError(f"Server did not start within {timeout} seconds.")

    def initialize_network(self, nodes_number: int):
        sequencer_address = None
        initialized_network_snapshot: SnapShotType = {}
        execution_cmds = {}
        for node_idx in range(nodes_number):
            keys = self.generate_keys()
            node_info = self.generate_node_info(node_idx=node_idx, keys=keys)
            if node_idx == 0:
                sequencer_address = node_info.id

            initialized_network_snapshot[node_info.id] = node_info
            execution_cmds[node_info.id] = self.prepare_node(node_idx=node_idx,
                                                             keys=keys,
                                                             sequencer_initial_address=sequencer_address)

        self.nodes_registry_client.add_snapshot(initialized_network_snapshot)

        for node_address, (cmd, env_variables) in execution_cmds.items():
            self.launch_node(cmd, env_variables)

        self.sequencer_address, self.network_nodes_state = sequencer_address, initialized_network_snapshot

    def transfer_state(self, next_network_nodes_number: int, nodes_last_index: int):
        current_network_nodes_number = len(self.network_nodes_state)
        next_network_state = copy.deepcopy(self.network_nodes_state)

        if current_network_nodes_number < next_network_nodes_number:
            first_new_node_idx = nodes_last_index + 1
            new_nodes_number = next_network_nodes_number - current_network_nodes_number
            new_nodes_cmds = {}
            for node_idx in range(first_new_node_idx, first_new_node_idx + new_nodes_number):
                keys = self.generate_keys()
                node_info = self.generate_node_info(node_idx=node_idx, keys=keys)
                next_network_state[node_info.id] = node_info

                new_nodes_cmds[node_info.id] = self.prepare_node(node_idx=node_idx,
                                                                 keys=keys,
                                                                 sequencer_initial_address=self.sequencer_address)

            self.nodes_registry_client.add_snapshot(next_network_state)
            for node_address, (cmd, env_variables) in new_nodes_cmds.items():
                self.launch_node(cmd, env_variables)

        self.network_nodes_state = next_network_state
        self.nodes_registry_client.add_snapshot(self.network_nodes_state)

    def simulate_network_nodes_transition(self):
        self.delete_directory_contents(self.simulation_config.DST_DIR)

        if not os.path.exists(self.simulation_config.DST_DIR):
            os.makedirs(self.simulation_config.DST_DIR)

        script_dir: str = os.path.dirname(os.path.abspath(__file__))
        parent_dir: str = os.path.dirname(script_dir)
        os.chdir(parent_dir)

        with open(file=self.simulation_config.APPS_FILE, mode="w", encoding="utf-8") as file:
            file.write(json.dumps({f"{self.simulation_config.APP_NAME}": {"url": "", "public_keys": []}}))

        self.initialize_network(self.simulation_config.TIMESERIES_NODES_COUNT[0])

        timeseries_nodes_last_idx = self.get_timeseries_last_node_idx()
        for next_network_state_idx in range(1, len(self.simulation_config.TIMESERIES_NODES_COUNT) - 1):
            time.sleep(6)
            self.transfer_state(
                next_network_nodes_number=self.simulation_config.TIMESERIES_NODES_COUNT[next_network_state_idx],
                nodes_last_index=timeseries_nodes_last_idx[next_network_state_idx - 1])

    @staticmethod
    def generate_transactions(batch_size: int) -> List[Dict]:
        return [
            {
                "operation": "foo",
                "serial": tx_num,
                "version": 6,
            } for tx_num in range(batch_size)
        ]

    def simulate_send_batches(self):
        sending_batches_count = 0
        while sending_batches_count < 100:
            if self.network_nodes_state and self.sequencer_address:
                random_node_address = random.choice(
                    list(set(list(self.network_nodes_state.keys())) - {self.sequencer_address}))
                node_socket = self.network_nodes_state[random_node_address].socket

                try:
                    string_data = json.dumps(self.generate_transactions(random.randint(200, 600)))
                    response: requests.Response = requests.put(
                        url=f"{node_socket}/node/{self.simulation_config.APP_NAME}/batches",
                        data=string_data,
                        headers={"Content-Type": "application/json"},
                    )
                    response.raise_for_status()
                    sending_batches_count += 1
                except RequestException as error:
                    print(f"Error sending batch of transactions: {error}")

            time.sleep(1)

        print('sending batches completed!')

    def run(self):
        self.nodes_registry_thread = threading.Thread(
            target=run_registry_server,
            args=(self.simulation_config.HISTORICAL_NODES_REGISTRY_HOST,
                  self.simulation_config.HISTORICAL_NODES_REGISTRY_PORT),
            daemon=True)
        self.nodes_registry_thread.start()

        try:
            self.wait_nodes_registry_server()
        except TimeoutError as e:
            print(f"Error: {e}")
            return
        print("Historical Nodes Registry server is running. Press Ctrl+C to stop.")

        self.network_transition_thread = threading.Thread(target=self.simulate_network_nodes_transition)
        self.send_batches_thread = threading.Thread(target=self.simulate_send_batches)

        self.network_transition_thread.start()
        self.send_batches_thread.start()

        self.network_transition_thread.join()
        self.send_batches_thread.join()

        self.shutdown_event.wait()


def main():
    DynamicNetworkSimulation(simulation_config=SimulationConfig()).run()


if __name__ == "__main__":
    main()
