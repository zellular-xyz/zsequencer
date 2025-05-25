import argparse
import hashlib
import json
import os
import subprocess
import time

from eigensdk.crypto.bls import attestation
from eth_account.signers.local import LocalAccount
from pydantic import BaseModel, ConfigDict
from web3 import Account

from common.logger import zlogger
from sabotage.schema import SabotageConf

DOCKER_NETWORK_NAME = "zsequencer_net"
SIMULATION_DATA_DIR = "./dist/e2e_test_data"


class Keys(BaseModel):
    bls_key: attestation.KeyPair
    ecdsa_key: LocalAccount
    address: str

    model_config = ConfigDict(arbitrary_types_allowed=True)


class NodeInfo(BaseModel):
    id: str
    pubkeyG2_X: tuple[int, int]
    pubkeyG2_Y: tuple[int, int]
    address: str
    socket: str
    stake: int


class ExecutionData(BaseModel):
    env_variables: dict


class SimulationConfig(BaseModel):
    shared_env_variables: dict[str, str]
    base_port: int
    node_num: int
    sabotages_config: dict[str, SabotageConf]


def load_simulation_config(config_path: str) -> SimulationConfig:
    """Load simulation configuration from a JSON file."""
    try:
        with open(config_path, "r") as f:
            config_data = json.load(f)
        return SimulationConfig(**config_data)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        zlogger.error(f"Error loading simulation config: {e}")
        raise


def generate_keys(idx: int) -> Keys:
    """Generate deterministic keys based on the provided index."""

    # Use SHA256 to generate deterministic hex string for BLS key
    seed = f"zsequencer_bls_{idx}".encode()
    hash_obj = hashlib.sha256(seed)
    bls_private_key = hash_obj.hexdigest()
    bls_key = attestation.new_key_pair_from_string(bls_private_key)

    # Use a different seed for ECDSA key to avoid using the same key
    ecdsa_seed = f"zsequencer_ecdsa_{idx}".encode()
    ecdsa_hash = hashlib.sha256(ecdsa_seed)
    ecdsa_private_key = ecdsa_hash.hexdigest()
    ecdsa_key = Account().from_key(ecdsa_private_key)

    return Keys(
        bls_key=bls_key,
        ecdsa_key=ecdsa_key,
        address=ecdsa_key.address.lower(),
    )


def generate_network_keys(network_nodes_num: int) -> tuple[str, list[Keys]]:
    """Generate deterministic keys for all nodes in the network."""
    network_keys = [generate_keys(idx) for idx in range(1, network_nodes_num + 1)]
    network_keys = sorted(network_keys, key=lambda network_key: network_key.address)
    sequencer_address = network_keys[0].address
    return sequencer_address, network_keys


def generate_node_info(
    node_idx: int,
    keys: Keys,
    base_port: int,
    stake: int = 10,
    node_host: str = "localhost",
) -> NodeInfo:
    """Generate node information based on keys and network settings."""
    pubkeyG2_X, pubkeyG2_Y = attestation.g2_to_tupple(keys.bls_key.pub_g2)
    return NodeInfo(
        id=keys.address,
        pubkeyG2_X=pubkeyG2_X,
        pubkeyG2_Y=pubkeyG2_Y,
        address=keys.address,
        socket=f"http://{node_host}:{str(base_port + node_idx)}",
        stake=stake,
    )


def ensure_docker_network() -> None:
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
        zlogger.error(f"Error managing Docker network: {e}")
        raise


def get_container_names() -> list[str]:
    """Get the names of all zsequencer node containers."""
    try:
        filter_arg = "name=zsequencer-node-"
        result = subprocess.run(
            ["docker", "ps", "-a", "--filter", filter_arg, "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            check=True,
        )

        container_names = result.stdout.strip().split("\n")
        return sorted(
            [name for name in container_names if name]
        )  # Filter out empty strings
    except subprocess.CalledProcessError as e:
        zlogger.error(f"Error getting container names: {e}")
        return []


def stop() -> None:
    """Stop and remove all zsequencer node containers."""
    container_names = get_container_names()

    if not container_names:
        zlogger.warning("No zsequencer containers found.")
        return

    zlogger.info(f"Stopping and removing {len(container_names)} containers...")

    for container_name in container_names:
        zlogger.info(f"Stopping container {container_name}...")

        subprocess.run(
            ["docker", "stop", container_name], check=False, stdout=subprocess.DEVNULL
        )
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            check=False,
            stdout=subprocess.DEVNULL,
        )

    zlogger.info("All zsequencer containers have been stopped and removed.")


def run_docker_container(
    image_name: str, container_name: str, env_variables: dict[str, str]
) -> None:
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
        env_variables["ZSEQUENCER_SABOTAGE_CONFIG_FILE"]: "/app/sabotage.json",
    }

    docker_env = {
        **env_variables,
        "ZSEQUENCER_BLS_KEY_FILE": "/app/bls_key.json",
        "ZSEQUENCER_ECDSA_KEY_FILE": "/app/ecdsa_key.json",
        "ZSEQUENCER_SNAPSHOT_PATH": "/db",
        "ZSEQUENCER_APPS_FILE": "/app/app.json",
        "ZSEQUENCER_NODES_FILE": "/app/nodes.json",
        "ZSEQUENCER_SABOTAGE_CONFIG_FILE": "/app/sabotage.json",
    }

    cmd = [
        "docker",
        "run",
        "--cap-add",
        "NET_ADMIN",
        "-d",
        "--name",
        container_name,
    ]
    cmd.extend(["--network", DOCKER_NETWORK_NAME])

    for host_path, container_path in volumes.items():
        cmd.extend(["-v", f"{host_path}:{container_path}"])

    for key, value in docker_env.items():
        cmd.extend(["-e", f"{key}={value}"])

    port = env_variables.get("ZSEQUENCER_PORT", "6000")
    cmd.extend(["-p", f"{port}:{port}"])
    cmd.append(image_name)

    try:
        # Use capture_output to suppress the container ID output
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        zlogger.error(f"Error starting container {container_name}: {e}")
        raise


def prepare_simulation_files(node_idx: int, keys: Keys) -> dict[str, str]:
    """Prepare node files in the simulation directory."""
    # Create node directory
    node_dir = os.path.join(SIMULATION_DATA_DIR, f"node_{node_idx}")
    if not os.path.exists(node_dir):
        os.makedirs(node_dir)

    # Save BLS key
    bls_key_file = os.path.join(node_dir, "bls_key.json")
    bls_key_pair = keys.bls_key
    bls_key_pair.save_to_file(bls_key_file, f"a{node_idx}")

    # Save ECDSA key
    ecdsa_key_file = os.path.join(node_dir, "ecdsa_key.json")
    encrypted_json = Account.encrypt(keys.ecdsa_key._private_key.hex(), f"b{node_idx}")
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
    shared_env_variables: dict[str, str],
    base_port: int,
) -> dict[str, str]:
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
        "ZSEQUENCER_INIT_SEQUENCER_ID": sequencer_address,
        "ZSEQUENCER_SABOTAGE_CONFIG_FILE": os.path.join(node_dir, "sabotage.json"),
    }


def start(config_path: str) -> None:
    """Start a network of zsequencer nodes based on the provided configuration."""
    # Load simulation configuration
    config = load_simulation_config(config_path)
    zlogger.info(f"Starting a network with {config.node_num} nodes...")

    # Delete old simulation directory and create a new one
    if not os.path.exists(SIMULATION_DATA_DIR):
        os.makedirs(SIMULATION_DATA_DIR)

    # Clean up existing containers
    stop()
    ensure_docker_network()

    # Generate network keys and prepare nodes
    sequencer_address, network_keys = generate_network_keys(config.node_num)
    nodes_info = {}
    nodes_execution_args = {}

    zlogger.info("Preparing node files and configurations...")

    # Prepare nodes
    for i, keys in enumerate(network_keys):
        idx = i + 1
        # Prepare node files
        node_files = prepare_simulation_files(idx, keys)

        # Write sabotage file
        with open(os.path.join(node_files["node_dir"], "sabotage.json"), "w") as f:
            json.dump(config.sabotages_config[str(idx)].dict(), f, indent=4)

        # Prepare environment variables
        env_vars = get_node_env_variables(
            idx,
            node_files["node_dir"],
            sequencer_address,
            config.shared_env_variables,
            config.base_port,
        )
        nodes_execution_args[keys.address] = ExecutionData(env_variables=env_vars)

        # Generate node info
        nodes_info[keys.address] = generate_node_info(
            node_idx=idx,
            keys=keys,
            base_port=config.base_port,
            node_host=env_vars["ZSEQUENCER_HOST"],
        ).dict()

    # Write configuration files
    with open(os.path.join(SIMULATION_DATA_DIR, "nodes.json"), "w") as f:
        json.dump(nodes_info, f, indent=4)

    with open(os.path.join(SIMULATION_DATA_DIR, "apps.json"), "w") as f:
        json.dump({"simple_app": {"url": "", "public_keys": []}}, f, indent=4)

    zlogger.info(f"Starting {config.node_num} containers...")

    # Start containers
    for i, node_id in enumerate(sorted(nodes_info.keys())):
        idx = i + 1
        container_name = f"zsequencer-node-{idx}"
        execution_data = nodes_execution_args[node_id]

        # Silently remove any existing container with the same name
        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)

        zlogger.info(f"  Starting node {idx}/{config.node_num}: {container_name}")

        # Use the existing run_docker_container function
        run_docker_container(
            image_name="zellular/zsequencer:latest",
            container_name=container_name,
            env_variables=execution_data.env_variables,
        )

        time.sleep(1)

    zlogger.info("\nNetwork started successfully!")
    zlogger.info(
        f"- Node ports: {config.base_port} to {config.base_port + config.node_num - 1}"
    )
    zlogger.info(f"- Sequencer: zsequencer-node-0 (running on port {config.base_port})")
    zlogger.info(f"- Configuration: {config_path}")
    zlogger.info("\nTo view logs: tests.e2e.run logs --terminal=<terminal>")
    zlogger.info("To stop the network: tests.e2e.run stop")


def show_logs(terminal_cmd: str) -> None:
    """Open terminals showing logs for all zsequencer node containers."""
    container_names = get_container_names()

    if not container_names:
        zlogger.warning("No zsequencer containers found.")
        return

    zlogger.info(f"Opening terminal windows for {len(container_names)} containers...")

    def get_terminal_command(terminal_type: str, container: str) -> list[str]:
        """Get the appropriate terminal command based on terminal type."""
        title = f"Logs: {container}"
        log_command = f"docker logs -f {container}; read -p 'Press Enter to close...'"

        if terminal_type == "gnome-terminal":
            return [terminal_type, "--", "bash", "-c", log_command]
        elif terminal_type in ["konsole", "terminator"]:
            return [terminal_type, "-e", f"bash -c '{log_command}'"]
        elif terminal_type == "tilix":
            return [terminal_type, "-t", title, "-e", f"bash -c '{log_command}'"]
        else:  # xterm or others
            return [terminal_type, "-T", title, "-e", f"bash -c '{log_command}'"]

    # Open a terminal for each container
    for container_name in container_names:
        cmd = get_terminal_command(terminal_cmd, container_name)
        subprocess.Popen(cmd)
        # Small delay to prevent terminals from overlapping too much

        time.sleep(0.5)

    zlogger.info("Terminal windows opened. Close them manually when done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run a zsequencer network simulation")
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # Start command
    start_parser = subparsers.add_parser("start", help="Start a network of nodes")
    start_parser.add_argument(
        "--config",
        type=str,
        default="tests/e2e/sample_config.json",
        help="Path to the simulation configuration file",
    )

    # Stop command
    stop_parser = subparsers.add_parser("stop", help="Stop all running containers")

    # Logs command
    logs_parser = subparsers.add_parser("logs", help="Show logs for containers")
    logs_parser.add_argument(
        "--terminal",
        type=str,
        choices=["gnome-terminal", "xterm", "konsole", "terminator", "tilix"],
        required=True,
        help="Terminal emulator to use",
    )

    args = parser.parse_args()

    # Default to start if no command is provided
    if args.command is None or args.command == "start":
        start(args.config)
    elif args.command == "stop":
        stop()
    elif args.command == "logs":
        show_logs(args.terminal)
