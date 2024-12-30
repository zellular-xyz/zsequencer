"""This script sets up and runs a simple app network for testing."""
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import json
import time
import secrets
import shutil
import subprocess
import threading
import socket
from pathlib import Path
from typing import Any, Optional
from historical_nodes_registry import NodesRegistryClient, NodeInfo, run_registry_server
from eigensdk.crypto.bls import attestation
from web3 import Account

NUM_INSTANCES: int = 3
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


def generate_privates_and_nodes_info() -> tuple[list[str], dict[str, Any]]:
    """Generate private keys and nodes information for the network."""
    nodes_info_dict: dict[str, Any] = {}
    bls_privates_list: list[str] = []
    ecdsa_privates_list: list[str] = []

    for i in range(NUM_INSTANCES):
        bls_private_key: str = secrets.token_hex(32)
        bls_privates_list.append(bls_private_key)
        bls_key_pair: attestation.KeyPair = attestation.new_key_pair_from_string(
            bls_private_key
        )
        ecdsa_private_key: str = secrets.token_hex(32)
        ecdsa_privates_list.append(ecdsa_private_key)
        address: str = Account().from_key(ecdsa_private_key).address.lower()
        nodes_info_dict[address] = {
            "id": address,
            "public_key_g2": bls_key_pair.pub_g2.getStr(10).decode("utf-8"),
            "address": address,
            "socket": f"http://127.0.0.1:{str(BASE_PORT + i + 1)}",
            "stake": 10,
        }

    return bls_privates_list, ecdsa_privates_list, nodes_info_dict


def generate_bash_command_file(
        command_name: str,
        command_args: str,
        env_variables: dict[str, str],
        bash_filename: Optional[str]
) -> None:
    """Run a command in a new terminal tab."""
    script_dir: str = os.path.dirname(os.path.abspath(__file__))
    parent_dir: str = os.path.dirname(script_dir)
    os.chdir(parent_dir)

    env_script = "export " + " ".join([f"{key}='{value}'" for key, value in env_variables.items()])
    command: str = f"python -u {command_name} {command_args}; echo; read -p 'Press enter to exit...'"
    full_command = f"{env_script} && {command}"

    if bash_filename is not None:
        file_path = os.path.join(BASE_DIRECTORY, bash_filename)
        if os.path.exists(file_path):
            os.remove(file_path)
        with open(file_path, "w+") as bash_file:
            bash_file.write(full_command)


def prepare_nodes() -> None:
    bls_privates_list, ecdsa_privates_list, nodes_info_dict = generate_privates_and_nodes_info()

    if not os.path.exists(DST_DIR):
        os.makedirs(DST_DIR)

    script_dir: str = os.path.dirname(os.path.abspath(__file__))
    parent_dir: str = os.path.dirname(script_dir)
    os.chdir(parent_dir)

    with open(file=APPS_FILE, mode="w", encoding="utf-8") as file:
        file.write(json.dumps({f"{APP_NAME}": {"url": "", "public_keys": []}}))

    '''
        Register initial nodes info on historical registry server to be fetch in future 
    '''
    nodes_registry_client = NodesRegistryClient(socket=HISTORICAL_NODES_REGISTRY_SOCKET)
    initial_snapshot = {
        id: NodeInfo(id=id,
                     public_key_g2=node_dict.get('public_key_g2'),
                     address=id,
                     socket=node_dict.get('socket'),
                     stake=node_dict.get('stake'))
        for id, node_dict in nodes_info_dict.items()
    }
    nodes_registry_client.add_snapshot(initial_snapshot)

    for i in range(NUM_INSTANCES):
        data_dir: str = f"{DST_DIR}/db_{i + 1}"
        if os.path.exists(data_dir):
            shutil.rmtree(data_dir)

        bls_key_file: str = f"{DST_DIR}/bls_key{i + 1}.json"
        bls_passwd: str = f'a{i + 1}'
        bls_key_pair: attestation.KeyPair = attestation.new_key_pair_from_string(
            bls_privates_list[i]
        )
        bls_key_pair.save_to_file(bls_key_file, bls_passwd)

        ecdsa_key_file: str = f"{DST_DIR}/ecdsa_key{i + 1}.json"
        ecdsa_passwd: str = f'b{i + 1}'
        encrypted_json = Account.encrypt(ecdsa_privates_list[i], ecdsa_passwd)
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
            "ZSEQUENCER_PORT": str(BASE_PORT + i + 1),
            "ZSEQUENCER_SNAPSHOT_CHUNK": str(ZSEQUENCER_SNAPSHOT_CHUNK),
            "ZSEQUENCER_REMOVE_CHUNK_BORDER": str(ZSEQUENCER_REMOVE_CHUNK_BORDER),
            "ZSEQUENCER_THRESHOLD_PERCENT": str(THRESHOLD_PERCENT),
            "ZSEQUENCER_SEND_TXS_INTERVAL": str(ZSEQUENCER_SEND_TXS_INTERVAL),
            "ZSEQUENCER_SYNC_INTERVAL": str(ZSEQUENCER_SYNC_INTERVAL),
            "ZSEQUENCER_FINALIZATION_TIME_BORDER": str(
                ZSEQUENCER_FINALIZATION_TIME_BORDER),
            "ZSEQUENCER_SIGNATURES_AGGREGATION_TIMEOUT": str(
                ZSEQUENCER_SIGNATURES_AGGREGATION_TIMEOUT),
            "ZSEQUENCER_FETCH_APPS_AND_NODES_INTERVAL": str(
                ZSEQUENCER_FETCH_APPS_AND_NODES_INTERVAL),
            "ZSEQUENCER_API_BATCHES_LIMIT": str(ZSEQUENCER_API_BATCHES_LIMIT),
            "ZSEQUENCER_INIT_SEQUENCER_ID": list(nodes_info_dict.keys())[0],
            "ZSEQUENCER_NODES_SOURCE": ZSEQUENCER_NODES_SOURCES[1],
            "ZSEQUENCER_REGISTER_OPERATOR": "false"
        })

        generate_bash_command_file(os.path.join(Path(__file__).parent.parent, "run.py"),
                                   f"{i + 1}",
                                   env_variables,
                                   f'node_{(i + 1)}.sh')

        nodes_file_path = os.path.join(BASE_DIRECTORY, f'node_{(i + 1)}.sh')
        subprocess.run(['chmod', '+x', nodes_file_path])


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

    prepare_nodes()

    # Wait until a shutdown signal is received
    print("Historical Nodes Registry server is running. Press Ctrl+C to stop.")
    shutdown_event.wait()
    print("Main program exiting.")


if __name__ == "__main__":
    main()
