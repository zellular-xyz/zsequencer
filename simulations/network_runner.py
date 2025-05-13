import hashlib
import json
import os
import subprocess
import time
from typing import Dict, List, Tuple, Any

from eigensdk.crypto.bls import attestation
from pydantic import BaseModel
from web3 import Account

# Constants
NETWORK_NODES_COUNT = 4
DOCKER_NETWORK_NAME = "zsequencer_net"
SIMULATION_DATA_DIR = './data'
BASE_NODE_PORT = 6005
BASE_PROXY_PORT = 7001


# Model definitions
class Keys(BaseModel):
    bls_private_key: str
    bls_key_pair: Any
    ecdsa_private_key: str


class KeyData(BaseModel):
    keys: Keys
    address: str


class NodeInfo(BaseModel):
    id: str
    pubkeyG2_X: tuple
    pubkeyG2_Y: tuple
    address: str
    socket: str
    stake: int


class ExecutionData(BaseModel):
    env_variables: Dict


# Load environment variables from .env.shared
def load_env_shared():
    env_vars = {}
    with open('.env.shared', 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                key, value = line.split('=', 1)
                env_vars[key.strip()] = value.strip()
    return env_vars


def generate_keys(idx: int) -> Keys:
    """Generate deterministic keys based on the provided index."""
    # Create a deterministic seed based on the index
    seed = f"zsequencer_node_{idx}".encode()

    # Use SHA256 to generate deterministic bytes
    hash_obj = hashlib.sha256(seed)
    deterministic_bytes = hash_obj.digest()

    # Generate deterministic private keys
    bls_private_key = deterministic_bytes[:32].hex()
    bls_key_pair = attestation.new_key_pair_from_string(bls_private_key)
    ecdsa_private_key = deterministic_bytes[32:].hex()

    return Keys(bls_private_key=bls_private_key,
                bls_key_pair=bls_key_pair,
                ecdsa_private_key=ecdsa_private_key)


def generate_network_keys(network_nodes_num: int) -> Tuple[str, List[KeyData]]:
    network_keys = []

    for _ in range(network_nodes_num):
        keys = generate_keys()
        address = Account().from_key(keys.ecdsa_private_key).address.lower()
        network_keys.append(KeyData(keys=keys, address=address))

    network_keys = sorted(network_keys, key=lambda network_key: network_key.address)
    sequencer_address = network_keys[0].address

    return sequencer_address, network_keys


def generate_node_info(node_idx: int, key_data: KeyData, stake: int = 10, node_host="localhost"):
    pubkeyG2_X, pubkeyG2_Y = attestation.g2_to_tupple(key_data.keys.bls_key_pair.pub_g2)
    return NodeInfo(id=key_data.address,
                    pubkeyG2_X=pubkeyG2_X,
                    pubkeyG2_Y=pubkeyG2_Y,
                    address=key_data.address,
                    socket=f"http://{node_host}:{str(BASE_NODE_PORT + node_idx)}",
                    stake=stake)


def ensure_docker_network():
    """Ensure the Docker network exists."""
    try:
        result = subprocess.run(['docker', 'network', 'inspect', DOCKER_NETWORK_NAME],
                                capture_output=True, text=True)
        if result.returncode != 0:
            subprocess.run(['docker', 'network', 'create', DOCKER_NETWORK_NAME], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error managing Docker network: {e}")
        raise


def clean_docker_containers(network_nodes_num: int):
    """Stop and remove all zsequencer node containers."""
    for idx in range(network_nodes_num):
        container_name = f"zsequencer-node-{idx}"
        try:
            subprocess.run(["docker", "stop", container_name], capture_output=True, check=False)
            subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, check=False)
        except subprocess.CalledProcessError as e:
            print(f"Error cleaning container {container_name}: {e}")


def run_docker_container(image_name: str, container_name: str, env_variables: dict):
    """Run a zsequencer node in a Docker container."""
    data_dir = env_variables['ZSEQUENCER_SNAPSHOT_PATH']
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)

    volumes = {
        env_variables['ZSEQUENCER_BLS_KEY_FILE']: '/app/bls_key.json',
        env_variables['ZSEQUENCER_ECDSA_KEY_FILE']: '/app/ecdsa_key.json',
        env_variables['ZSEQUENCER_SNAPSHOT_PATH']: '/db',
        env_variables['ZSEQUENCER_APPS_FILE']: '/app/app.json',
        env_variables['ZSEQUENCER_NODES_FILE']: '/app/nodes.json',
        env_variables['ZSEQUENCER_SEQUENCER_SABOTAGE_SIMULATION_TIMESERIES_NODES_STATE_FILE']:
            '/app/sabotage_simulation_timeseries.json',
    }

    docker_env = {
        **env_variables,
        **load_env_shared(),  # Include shared environment variables
        'ZSEQUENCER_BLS_KEY_FILE': '/app/bls_key.json',
        'ZSEQUENCER_ECDSA_KEY_FILE': '/app/ecdsa_key.json',
        'ZSEQUENCER_SNAPSHOT_PATH': '/db',
        'ZSEQUENCER_APPS_FILE': '/app/app.json',
        'ZSEQUENCER_NODES_FILE': '/app/nodes.json',
        'ZSEQUENCER_SEQUENCER_SABOTAGE_SIMULATION_TIMESERIES_NODES_STATE_FILE':
            '/app/sabotage_simulation_timeseries.json'
    }

    cmd = ["docker", "run", "-d", "--name", container_name]
    cmd.extend(["--network", DOCKER_NETWORK_NAME])

    for host_path, container_path in volumes.items():
        cmd.extend(["-v", f"{host_path}:{container_path}"])

    for key, value in docker_env.items():
        cmd.extend(["-e", f"{key}={value}"])

    port = env_variables.get('ZSEQUENCER_PORT', '6000')
    cmd.extend(["-p", f"{port}:{port}"])
    cmd.append(image_name)

    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error starting container {container_name}: {e}")
        raise


def prepare_simulation_files(node_idx: int, keys: Keys):
    """Prepare node files in the simulation directory."""
    # Create node directory
    node_dir = os.path.join(SIMULATION_DATA_DIR, f'node_{node_idx}')
    if not os.path.exists(node_dir):
        os.makedirs(node_dir)

    # Save BLS key
    bls_key_file = os.path.join(node_dir, 'bls_key.json')
    bls_key_pair = attestation.new_key_pair_from_string(keys.bls_private_key)
    bls_key_pair.save_to_file(bls_key_file, f'a{node_idx}')

    # Save ECDSA key
    ecdsa_key_file = os.path.join(node_dir, 'ecdsa_key.json')
    encrypted_json = Account.encrypt(keys.ecdsa_private_key, f'b{node_idx}')
    with open(ecdsa_key_file, 'w') as f:
        json.dump(encrypted_json, f)

    return {
        'node_dir': node_dir,
        'bls_key_file': bls_key_file,
        'ecdsa_key_file': ecdsa_key_file
    }


def get_node_env_variables(node_idx: int, node_dir: str, sequencer_address: str) -> dict:
    """Generate environment variables for a node."""
    shared_env = load_env_shared()

    return {
        **shared_env,
        "ZSEQUENCER_APPS_FILE": os.path.join(SIMULATION_DATA_DIR, "apps.json"),
        "ZSEQUENCER_NODES_FILE": os.path.join(SIMULATION_DATA_DIR, "nodes.json"),
        "ZSEQUENCER_HOST": f"zsequencer-node-{node_idx}",
        "ZSEQUENCER_PORT": str(BASE_NODE_PORT + node_idx),
        "ZSEQUENCER_SNAPSHOT_PATH": os.path.join(node_dir, "db"),
        "ZSEQUENCER_BLS_KEY_FILE": os.path.join(node_dir, "bls_key.json"),
        "ZSEQUENCER_BLS_KEY_PASSWORD": f"a{node_idx}",
        "ZSEQUENCER_ECDSA_KEY_FILE": os.path.join(node_dir, "ecdsa_key.json"),
        "ZSEQUENCER_ECDSA_KEY_PASSWORD": f"b{node_idx}",
        "ZSEQUENCER_PROXY_PORT": str(BASE_PROXY_PORT + node_idx),
        "ZSEQUENCER_INIT_SEQUENCER_ID": sequencer_address,
        "ZSEQUENCER_SEQUENCER_SABOTAGE_SIMULATION_TIMESERIES_NODES_STATE_FILE":
            os.path.join(SIMULATION_DATA_DIR, "sabotage_nodes_state.json")
    }


def main(network_nodes_num=NETWORK_NODES_COUNT):
    # Ensure simulation directory exists
    if not os.path.exists(SIMULATION_DATA_DIR):
        os.makedirs(SIMULATION_DATA_DIR)

    # Clean up existing containers
    clean_docker_containers(network_nodes_num)
    ensure_docker_network()

    # Generate network keys and prepare nodes
    sequencer_address, network_keys = generate_network_keys(network_nodes_num)
    nodes_info = {}
    nodes_execution_args = {}
    sabotage_timeseries_nodes = {}

    # Prepare nodes
    for idx, key_data in enumerate(network_keys):
        # Prepare node files
        node_files = prepare_simulation_files(idx, key_data.keys)
        container_name = f'zsequencer-node-{idx}'

        # Generate node info
        nodes_info[key_data.address] = generate_node_info(
            node_idx=idx,
            key_data=key_data,
            node_host=container_name
        ).dict()

        # Generate sabotage timeseries
        up_duration = 20 + (idx * 10)
        sabotage_timeseries_nodes[key_data.address] = [
            {"time_duration": up_duration, "up": True},
            {"time_duration": 10, "up": False},
            {"time_duration": 100, "up": True}
        ]

        # Prepare environment variables
        env_vars = get_node_env_variables(idx, node_files['node_dir'], sequencer_address)
        nodes_execution_args[key_data.address] = ExecutionData(env_variables=env_vars)

    # Write configuration files
    with open(os.path.join(SIMULATION_DATA_DIR, 'nodes.json'), 'w') as f:
        json.dump(nodes_info, f, indent=4)

    with open(os.path.join(SIMULATION_DATA_DIR, 'sabotage_nodes_state.json'), 'w') as f:
        json.dump(sabotage_timeseries_nodes, f, indent=4)

    with open(os.path.join(SIMULATION_DATA_DIR, 'apps.json'), 'w') as f:
        json.dump({
            "simple_app": {
                "url": "",
                "public_keys": []
            }
        }, f, indent=4)

    # Start containers
    for idx, node_id in enumerate(sorted(nodes_info.keys())):
        container_name = f"zsequencer-node-{idx}"
        execution_data = nodes_execution_args[node_id]

        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)
        run_docker_container(
            image_name="zellular/zsequencer:latest",
            container_name=container_name,
            env_variables=execution_data.env_variables
        )
        time.sleep(1)


if __name__ == "__main__":
    main()
