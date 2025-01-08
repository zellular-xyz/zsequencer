"""This script sets up and runs a simple app network for testing."""
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import json
import time
import secrets
import shutil
import threading
import socket
from pathlib import Path
from typing import Any, Dict, Tuple
from functools import reduce
from historical_nodes_registry import (NodesRegistryClient,
                                       NodeInfo,
                                       SnapShotType,
                                       run_registry_server)
from eigensdk.crypto.bls import attestation
from web3 import Account

TIMESERIES_NODES_COUNT = [3, 5, 7, 10]
TIMESERIES_LAST_NODE_INDEX = reduce(lambda acc,
                                           i: acc +
                                              [acc[-1] + (TIMESERIES_NODES_COUNT[i] - TIMESERIES_NODES_COUNT[i - 1])
                                               if TIMESERIES_NODES_COUNT[i - 1] < TIMESERIES_NODES_COUNT[i]
                                               else acc[-1]], range(1, len(TIMESERIES_NODES_COUNT)),
                                    [TIMESERIES_NODES_COUNT[0] - 1])
NUM_INSTANCES: int = 3
HOST = "http://127.0.0.1"
BASE_PORT: int = 6000
THRESHOLD_PERCENT: int = 67
DST_DIR: str = "/tmp/zellular_dev_net"
APPS_FILE: str = "/tmp/zellular_dev_net/apps.json"
HISTORICAL_NODES_REGISTRY_HOST: str = "localhost"
HISTORICAL_NODES_REGISTRY_PORT: int = 8000
HISTORICAL_NODES_REGISTRY_SOCKET: str = f"{HISTORICAL_NODES_REGISTRY_HOST}:{int(HISTORICAL_NODES_REGISTRY_PORT)}"
ZSEQUENCER_SNAPSHOT_CHUNK: int = 1000
ZSEQUENCER_REMOVE_CHUNK_BORDER: int = 3
ZSEQUENCER_SEND_TXS_INTERVAL: float = 0.05
ZSEQUENCER_SYNC_INTERVAL: float = 0.05
ZSEQUENCER_FINALIZATION_TIME_BORDER: int = 10
ZSEQUENCER_SIGNATURES_AGGREGATION_TIMEOUT = 5
ZSEQUENCER_FETCH_APPS_AND_NODES_INTERVAL = 30
ZSEQUENCER_API_BATCHES_LIMIT = 100
ZSEQUENCER_NODES_SOURCES = ["file",
                            "historical_nodes_registry",
                            "eigenlayer"]
APP_NAME: str = "simple_app"
BASE_DIRECTORY = './examples'
nodes_registry_client = NodesRegistryClient(socket=HISTORICAL_NODES_REGISTRY_SOCKET)


def generate_keys() -> Dict:
    bls_private_key: str = secrets.token_hex(32)
    bls_key_pair: attestation.KeyPair = attestation.new_key_pair_from_string(bls_private_key)
    ecdsa_private_key: str = secrets.token_hex(32)

    return dict(bls_private_key=bls_private_key,
                bls_key_pair=bls_key_pair,
                ecdsa_private_key=ecdsa_private_key)


def generate_node_info(node_idx: int, keys: Dict) -> NodeInfo:
    bls_private_key, bls_key_pair, ecdsa_private_key = (keys.get('bls_private_key'),
                                                        keys.get('bls_key_pair'),
                                                        keys.get('ecdsa_private_key'))
    address = Account().from_key(ecdsa_private_key).address.lower()

    return NodeInfo(id=address,
                    public_key_g2=bls_key_pair.pub_g2.getStr(10).decode("utf-8"),
                    address=address,
                    socket=f"{HOST}:{str(BASE_PORT + node_idx)}",
                    stake=10)


def generate_node_execution_command(command_name: str, command_args: str) -> str:
    """Run a command in a new terminal tab."""
    script_dir: str = os.path.dirname(os.path.abspath(__file__))
    parent_dir: str = os.path.dirname(script_dir)
    os.chdir(parent_dir)

    return f"python -u {command_name} {command_args}; echo; read -p 'Press enter to exit...'"


def prepare_node(node_idx: int,
                 keys: Dict,
                 sequencer_initial_address: str) -> Tuple[str, Dict]:
    bls_private_key, bls_key_pair, ecdsa_private_key = (keys.get('bls_private_key'),
                                                        keys.get('bls_key_pair'),
                                                        keys.get('ecdsa_private_key'))

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

    # Create environment variables for a node instance
    env_variables: dict[str, Any] = os.environ.copy()
    env_variables.update({
        "ZSEQUENCER_BLS_KEY_FILE": bls_key_file,
        "ZSEQUENCER_BLS_KEY_PASSWORD": bls_passwd,
        "ZSEQUENCER_ECDSA_KEY_FILE": ecdsa_key_file,
        "ZSEQUENCER_ECDSA_KEY_PASSWORD": ecdsa_passwd,
        "ZSEQUENCER_APPS_FILE": APPS_FILE,
        "ZSEQUENCER_SNAPSHOT_PATH": data_dir,
        "ZSEQUENCER_HISTORICAL_NODES_REGISTRY": HISTORICAL_NODES_REGISTRY_SOCKET,
        "ZSEQUENCER_PORT": str(BASE_PORT + node_idx),
        "ZSEQUENCER_SNAPSHOT_CHUNK": str(ZSEQUENCER_SNAPSHOT_CHUNK),
        "ZSEQUENCER_REMOVE_CHUNK_BORDER": str(ZSEQUENCER_REMOVE_CHUNK_BORDER),
        "ZSEQUENCER_THRESHOLD_PERCENT": str(THRESHOLD_PERCENT),
        "ZSEQUENCER_SEND_TXS_INTERVAL": str(ZSEQUENCER_SEND_TXS_INTERVAL),
        "ZSEQUENCER_SYNC_INTERVAL": str(ZSEQUENCER_SYNC_INTERVAL),
        "ZSEQUENCER_FINALIZATION_TIME_BORDER": str(ZSEQUENCER_FINALIZATION_TIME_BORDER),
        "ZSEQUENCER_SIGNATURES_AGGREGATION_TIMEOUT": str(ZSEQUENCER_SIGNATURES_AGGREGATION_TIMEOUT),
        "ZSEQUENCER_FETCH_APPS_AND_NODES_INTERVAL": str(ZSEQUENCER_FETCH_APPS_AND_NODES_INTERVAL),
        "ZSEQUENCER_API_BATCHES_LIMIT": str(ZSEQUENCER_API_BATCHES_LIMIT),
        "ZSEQUENCER_INIT_SEQUENCER_ID": sequencer_initial_address,
        "ZSEQUENCER_NODES_SOURCE": ZSEQUENCER_NODES_SOURCES[1],
        "ZSEQUENCER_REGISTER_OPERATOR": "false",
        "ZSEQUENCER_VERSION": "v0.0.12",
        "ZSEQUENCER_NODES_FILE": ""})

    return (generate_node_execution_command(os.path.join(Path(__file__).parent.parent), "run.py"),
            env_variables)


def transfer_state(current_network_nodes_state: SnapShotType,
                   next_network_nodes_number: int,
                   nodes_last_index: int,
                   sequencer_address: str) -> SnapShotType:
    current_network_nodes_number = len(current_network_nodes_state)
    next_network_state = current_network_nodes_state.copy()

    # Todo: Handle killing sessions for simulating node exit from network
    if current_network_nodes_number < next_network_nodes_number:
        first_new_node_idx = nodes_last_index + 1
        new_nodes_number = next_network_nodes_number - current_network_nodes_number
        for node_idx in range(first_new_node_idx, first_new_node_idx + new_nodes_number):
            keys = generate_keys()
            node_info = generate_node_info(node_idx=node_idx, keys=keys)
            next_network_state[node_info.id] = node_info

            prepare_node(node_idx=node_idx,
                         keys=keys,
                         sequencer_initial_address=sequencer_address)

    return next_network_state


def initialize_network(nodes_number: int) -> Tuple[str, SnapShotType]:
    sequencer_address = None
    initialized_network_snapshot: SnapShotType = {}
    execution_cmds = {}
    for node_idx in range(nodes_number):
        keys = generate_keys()
        node_info = generate_node_info(node_idx=node_idx, keys=keys)
        if node_idx == 0:
            sequencer_address = node_info.id

        initialized_network_snapshot[node_info.id] = node_info
        execution_cmds[node_info.id] = prepare_node(node_idx=node_idx,
                                                    keys=keys,
                                                    sequencer_initial_address=sequencer_address)

    nodes_registry_client.add_snapshot(initialized_network_snapshot)
    return sequencer_address, initialized_network_snapshot


def simulate_network():
    if not os.path.exists(DST_DIR):
        os.makedirs(DST_DIR)

    script_dir: str = os.path.dirname(os.path.abspath(__file__))
    parent_dir: str = os.path.dirname(script_dir)
    os.chdir(parent_dir)

    with open(file=APPS_FILE, mode="w", encoding="utf-8") as file:
        file.write(json.dumps({f"{APP_NAME}": {"url": "", "public_keys": []}}))

    sequencer_address, network_nodes_state = initialize_network(TIMESERIES_NODES_COUNT[0])

    for next_network_state_idx in range(1, len(TIMESERIES_NODES_COUNT) - 1):
        time.sleep(2)

        network_nodes_state = transfer_state(
            current_network_nodes_state=network_nodes_state,
            next_network_nodes_number=TIMESERIES_NODES_COUNT[next_network_state_idx],
            nodes_last_index=TIMESERIES_LAST_NODE_INDEX[next_network_state_idx - 1],
            sequencer_address=sequencer_address
        )
        nodes_registry_client.add_snapshot(network_nodes_state)


def wait_for_server(host: str, port: int, timeout: float = 20.0, interval: float = 0.5) -> None:
    """Wait for the server to be up and running."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            with socket.create_connection((host, port), timeout=interval):
                print(f"Server is up and running on {host}:{port}")
                return
        except (socket.timeout, ConnectionRefusedError):
            print(f"Waiting for server at {host}:{port}...")
            time.sleep(interval)
    raise TimeoutError(f"Server did not start within {timeout} seconds.")


shutdown_event = threading.Event()


def signal_handler(signum, frame):
    """Handle termination signals gracefully."""
    print("\nReceived termination signal. Shutting down...")
    shutdown_event.set()


def wait_for_server(host: str, port: int) -> None:
    """Wait for the server to be up and running."""
    while not shutdown_event.is_set():
        try:
            with socket.create_connection((host, port), timeout=1):
                print(f"Server is up and running on {host}:{port}")
                return
        except (socket.timeout, ConnectionRefusedError):
            print(f"Waiting for server at {host}:{port}...")
            time.sleep(0.5)


def main():
    registry_thread = threading.Thread(
        target=run_registry_server,
        args=(HISTORICAL_NODES_REGISTRY_HOST, HISTORICAL_NODES_REGISTRY_PORT),
        daemon=True)
    registry_thread.start()

    # Wait for the server to be ready
    try:
        wait_for_server(HISTORICAL_NODES_REGISTRY_HOST, HISTORICAL_NODES_REGISTRY_PORT)
    except TimeoutError as e:
        print(f"Error: {e}")
        return

    simulate_network()

    # Wait until a shutdown signal is received
    print("Historical Nodes Registry server is running. Press Ctrl+C to stop.")
    shutdown_event.wait()
    print("Main program exiting.")


if __name__ == "__main__":
    main()
