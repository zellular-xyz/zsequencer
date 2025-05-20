import hashlib
import json
import os
import subprocess
import time
from typing import Any, Dict, List, Tuple

from eigensdk.crypto.bls import attestation
from pydantic import BaseModel
from web3 import Account

# Constants
DOCKER_NETWORK_NAME = "zsequencer_net"
SIMULATION_DATA_DIR = "./data"
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


class SimulationConfig(BaseModel):
    shared_env_variables: Dict[str, Any]
    base_port: int
    node_num: int
    sabotages_config: Dict[str, List[Dict[str, Any]]]


def load_simulation_config(config_path: str) -> SimulationConfig:
    """Load simulation configuration from a JSON file."""
    try:
        with open(config_path, "r") as f:
            config_data = json.load(f)
        return SimulationConfig(**config_data)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        print(f"Error loading simulation config: {e}")
        raise


def generate_keys(idx: int) -> Keys:
    """Generate deterministic keys based on the provided index."""
    # Create a deterministic seed based on the index
    seed = f"zsequencer_node_{idx}".encode()

    # Use SHA256 to generate deterministic hex string for BLS key
    hash_obj = hashlib.sha256(seed)
    bls_private_key = hash_obj.hexdigest()
    bls_key_pair = attestation.new_key_pair_from_string(bls_private_key)

    # Use a different seed for ECDSA key to avoid using the same key
    ecdsa_seed = f"zsequencer_ecdsa_{idx}".encode()
    ecdsa_hash = hashlib.sha256(ecdsa_seed)
    ecdsa_private_key = ecdsa_hash.hexdigest()

    return Keys(
        bls_private_key=bls_private_key,
        bls_key_pair=bls_key_pair,
        ecdsa_private_key=ecdsa_private_key,
    )


def generate_network_keys(network_nodes_num: int) -> Tuple[str, List[KeyData]]:
    network_keys = []

    for idx in range(network_nodes_num):
        keys = generate_keys(idx)  # Pass the index to generate_keys
        address = Account().from_key(keys.ecdsa_private_key).address.lower()
        network_keys.append(KeyData(keys=keys, address=address))

    network_keys = sorted(network_keys, key=lambda network_key: network_key.address)
    sequencer_address = network_keys[0].address

    return sequencer_address, network_keys


def generate_node_info(
    node_idx: int,
    key_data: KeyData,
    base_port: int,
    stake: int = 10,
    node_host="localhost",
):
    pubkeyG2_X, pubkeyG2_Y = attestation.g2_to_tupple(key_data.keys.bls_key_pair.pub_g2)
    return NodeInfo(
        id=key_data.address,
        pubkeyG2_X=pubkeyG2_X,
        pubkeyG2_Y=pubkeyG2_Y,
        address=key_data.address,
        socket=f"http://{node_host}:{str(base_port + node_idx)}",
        stake=stake,
    )


def ensure_docker_network():
    """Ensure the Docker network exists."""
    try:
        result = subprocess.run(
            ["docker", "network", "inspect", DOCKER_NETWORK_NAME],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            subprocess.run(
                ["docker", "network", "create", DOCKER_NETWORK_NAME], check=True
            )
    except subprocess.CalledProcessError as e:
        print(f"Error managing Docker network: {e}")
        raise


def clean_docker_containers(network_nodes_num: int):
    """Stop and remove all zsequencer node containers."""
    for idx in range(network_nodes_num):
        container_name = f"zsequencer-node-{idx}"
        try:
            subprocess.run(
                ["docker", "stop", container_name], capture_output=True, check=False
            )
            subprocess.run(
                ["docker", "rm", "-f", container_name], capture_output=True, check=False
            )
        except subprocess.CalledProcessError as e:
            print(f"Error cleaning container {container_name}: {e}")


def run_docker_container(image_name: str, container_name: str, env_variables: dict):
    """Run a zsequencer node in a Docker container."""
    data_dir = env_variables["ZSEQUENCER_SNAPSHOT_PATH"]
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)

    volumes = {
        env_variables["ZSEQUENCER_BLS_KEY_FILE"]: "/app/bls_key.json",
        env_variables["ZSEQUENCER_ECDSA_KEY_FILE"]: "/app/ecdsa_key.json",
        env_variables["ZSEQUENCER_SNAPSHOT_PATH"]: "/db",
        env_variables["ZSEQUENCER_APPS_FILE"]: "/app/app.json",
        env_variables["ZSEQUENCER_NODES_FILE"]: "/app/nodes.json",
        env_variables[
            "ZSEQUENCER_SEQUENCER_SABOTAGE_SIMULATION_TIMESERIES_NODES_STATE_FILE"
        ]: "/app/sabotage_simulation_timeseries.json",
    }

    docker_env = {
        **env_variables,
        "ZSEQUENCER_BLS_KEY_FILE": "/app/bls_key.json",
        "ZSEQUENCER_ECDSA_KEY_FILE": "/app/ecdsa_key.json",
        "ZSEQUENCER_SNAPSHOT_PATH": "/db",
        "ZSEQUENCER_APPS_FILE": "/app/app.json",
        "ZSEQUENCER_NODES_FILE": "/app/nodes.json",
        "ZSEQUENCER_SEQUENCER_SABOTAGE_SIMULATION_TIMESERIES_NODES_STATE_FILE": "/app/sabotage_simulation_timeseries.json",
    }

    cmd = ["docker", "run", "-d", "--name", container_name]
    cmd.extend(["--network", DOCKER_NETWORK_NAME])

    for host_path, container_path in volumes.items():
        cmd.extend(["-v", f"{host_path}:{container_path}"])

    for key, value in docker_env.items():
        cmd.extend(["-e", f"{key}={value}"])

    port = env_variables.get("ZSEQUENCER_PORT", "6000")
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
    node_dir = os.path.join(SIMULATION_DATA_DIR, f"node_{node_idx}")
    if not os.path.exists(node_dir):
        os.makedirs(node_dir)

    # Save BLS key
    bls_key_file = os.path.join(node_dir, "bls_key.json")
    bls_key_pair = attestation.new_key_pair_from_string(keys.bls_private_key)
    bls_key_pair.save_to_file(bls_key_file, f"a{node_idx}")

    # Save ECDSA key
    ecdsa_key_file = os.path.join(node_dir, "ecdsa_key.json")
    encrypted_json = Account.encrypt(keys.ecdsa_private_key, f"b{node_idx}")
    with open(ecdsa_key_file, "w") as f:
        json.dump(encrypted_json, f)

    return {
        "node_dir": node_dir,
        "bls_key_file": bls_key_file,
        "ecdsa_key_file": ecdsa_key_file,
    }


def get_node_env_variables(
    node_idx: int,
    node_dir: str,
    sequencer_address: str,
    shared_env_variables: Dict[str, Any],
    base_port: int,
) -> dict:
    """Generate environment variables for a node."""
    return {
        **shared_env_variables,  # Only include shared environment variables from config
        "ZSEQUENCER_APPS_FILE": os.path.join(SIMULATION_DATA_DIR, "apps.json"),
        "ZSEQUENCER_NODES_FILE": os.path.join(SIMULATION_DATA_DIR, "nodes.json"),
        "ZSEQUENCER_HOST": f"zsequencer-node-{node_idx}",
        "ZSEQUENCER_PORT": str(base_port + node_idx),
        "ZSEQUENCER_SNAPSHOT_PATH": os.path.join(node_dir, "db"),
        "ZSEQUENCER_BLS_KEY_FILE": os.path.join(node_dir, "bls_key.json"),
        "ZSEQUENCER_BLS_KEY_PASSWORD": f"a{node_idx}",
        "ZSEQUENCER_ECDSA_KEY_FILE": os.path.join(node_dir, "ecdsa_key.json"),
        "ZSEQUENCER_ECDSA_KEY_PASSWORD": f"b{node_idx}",
        "ZSEQUENCER_PROXY_PORT": str(BASE_PROXY_PORT + node_idx),
        "ZSEQUENCER_INIT_SEQUENCER_ID": sequencer_address,
        "ZSEQUENCER_SEQUENCER_SABOTAGE_SIMULATION_TIMESERIES_NODES_STATE_FILE": os.path.join(
            SIMULATION_DATA_DIR, "sabotage_nodes_state.json"
        ),
    }


def main(config_path: str = "./simulation-config.json"):
    # Load simulation configuration
    config = load_simulation_config(config_path)

    # Ensure simulation directory exists
    if not os.path.exists(SIMULATION_DATA_DIR):
        os.makedirs(SIMULATION_DATA_DIR)

    # Clean up existing containers
    clean_docker_containers(config.node_num)
    ensure_docker_network()

    # Generate network keys and prepare nodes
    sequencer_address, network_keys = generate_network_keys(config.node_num)
    nodes_info = {}
    nodes_execution_args = {}
    sabotage_timeseries_nodes = {}

    # Prepare nodes
    for idx, key_data in enumerate(network_keys):
        # Prepare node files
        node_files = prepare_simulation_files(idx, key_data.keys)
        container_name = f"zsequencer-node-{idx}"

        # Generate node info
        nodes_info[key_data.address] = generate_node_info(
            node_idx=idx,
            key_data=key_data,
            base_port=config.base_port,
            node_host=container_name,
        ).dict()

        # Get sabotage timeseries from config
        # Use node index as key if available, otherwise use default
        sabotage_key = str(idx)
        if sabotage_key in config.sabotages_config:
            sabotage_timeseries_nodes[key_data.address] = config.sabotages_config[
                sabotage_key
            ]
        else:
            # Default sabotage config if not specified
            sabotage_timeseries_nodes[key_data.address] = [
                {"time_duration": 1000, "up": True},
                {"time_duration": 10, "up": False},
                {"time_duration": 100, "up": True},
            ]

        # Prepare environment variables
        env_vars = get_node_env_variables(
            idx,
            node_files["node_dir"],
            sequencer_address,
            config.shared_env_variables,
            config.base_port,
        )
        nodes_execution_args[key_data.address] = ExecutionData(env_variables=env_vars)

    # Write configuration files
    with open(os.path.join(SIMULATION_DATA_DIR, "nodes.json"), "w") as f:
        json.dump(nodes_info, f, indent=4)

    with open(os.path.join(SIMULATION_DATA_DIR, "sabotage_nodes_state.json"), "w") as f:
        json.dump(sabotage_timeseries_nodes, f, indent=4)

    with open(os.path.join(SIMULATION_DATA_DIR, "apps.json"), "w") as f:
        json.dump({"simple_app": {"url": "", "public_keys": []}}, f, indent=4)

    # Start containers
    for idx, node_id in enumerate(sorted(nodes_info.keys())):
        container_name = f"zsequencer-node-{idx}"
        execution_data = nodes_execution_args[node_id]

        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)
        run_docker_container(
            image_name="zellular/zsequencer:latest",
            container_name=container_name,
            env_variables=execution_data.env_variables,
        )
        time.sleep(1)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run a zsequencer network simulation")
    parser.add_argument(
        "--config",
        type=str,
        default="simulations/simulation-config.json",
        help="Path to the simulation configuration file",
    )

    args = parser.parse_args()
    main(args.config)
