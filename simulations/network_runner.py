import json
import os
import subprocess
import time

import simulations.utils as simulations_utils
from simulations.config import SimulationConfig, ExecutionData

NETWORK_NODES_COUNT = 4
DOCKER_NETWORK_NAME = "zsequencer_net"


def ensure_docker_network():
    """Ensure the Docker network exists."""
    try:
        # Check if network exists
        result = subprocess.run(['docker', 'network', 'inspect', DOCKER_NETWORK_NAME],
                                capture_output=True, text=True)
        if result.returncode != 0:
            # Create network if it doesn't exist
            subprocess.run(['docker', 'network', 'create', DOCKER_NETWORK_NAME], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error managing Docker network: {e}")
        raise


def run_docker_container(image_name: str, container_name: str, env_variables: dict):
    """Run a zsequencer node in a Docker container."""

    # Get the data directory path from simulations config
    data_dir = env_variables['ZSEQUENCER_SNAPSHOT_PATH']
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)

    # Prepare volume mappings as a dictionary
    volumes = {
        env_variables['ZSEQUENCER_BLS_KEY_FILE']: '/app/bls_key.json',
        env_variables['ZSEQUENCER_ECDSA_KEY_FILE']: '/app/ecdsa_key.json',
        env_variables['ZSEQUENCER_SNAPSHOT_PATH']: '/db',
        env_variables['ZSEQUENCER_APPS_FILE']: '/app/app.json',
        env_variables['ZSEQUENCER_NODES_FILE']: '/app/nodes.json'
    }

    # Prepare environment variables as a dictionary
    docker_env = {
        **env_variables,
        'ZSEQUENCER_BLS_KEY_FILE': '/app/bls_key.json',
        'ZSEQUENCER_ECDSA_KEY_FILE': '/app/ecdsa_key.json',
        'ZSEQUENCER_SNAPSHOT_PATH': '/db',
        'ZSEQUENCER_APPS_FILE': '/app/app.json',
        'ZSEQUENCER_NODES_FILE': '/app/nodes.json'
    }

    # Construct docker run command
    cmd = ["docker", "run", "-d", "--name", container_name]

    # Add network
    cmd.extend(["--network", DOCKER_NETWORK_NAME])

    # Add volumes from dictionary
    for host_path, container_path in volumes.items():
        cmd.extend(["-v", f"{host_path}:{container_path}"])

    # Add environment variables from dictionary
    for key, value in docker_env.items():
        cmd.extend(["-e", f"{key}={value}"])

    # Add port mapping
    port = env_variables.get('ZSEQUENCER_PORT', '6000')
    cmd.extend(["-p", f"{port}:{port}"])

    # Add image name
    cmd.append(image_name)

    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error starting container {container_name}: {e}")
        raise


def clean_docker_containers(network_nodes_num: int):
    """Stop and remove all zsequencer node containers."""
    for idx in range(network_nodes_num):
        container_name = f"zsequencer-node-{idx}"
        try:
            # Stop container if running
            subprocess.run(["docker", "stop", container_name],
                           capture_output=True, check=False)
            # Remove container
            subprocess.run(["docker", "rm", "-f", container_name],
                           capture_output=True, check=False)
        except subprocess.CalledProcessError as e:
            print(f"Error cleaning container {container_name}: {e}")


def main(network_nodes_num=NETWORK_NODES_COUNT):
    # Clean up existing containers
    clean_docker_containers(network_nodes_num)

    # Ensure Docker network exists
    ensure_docker_network()

    simulation_conf = SimulationConfig(
        ZSEQUENCER_NODES_SOURCE="file",
        BASE_PORT=6005,
        ZSEQUENCER_BANDWIDTH_KB_PER_WINDOW=1000_000,
        ZSEQUENCER_SNAPSHOT_CHUNK_SIZE_KB=2000
    )
    simulations_utils.remove_directory(simulation_conf.DST_DIR)
    sequencer_address, network_keys = simulations_utils.generate_network_keys(network_nodes_num=network_nodes_num)
    nodes_execution_args = {}
    nodes_info = {}

    for idx, key_data in enumerate(network_keys):
        simulation_conf.prepare_node(node_idx=idx, keys=key_data.keys)
        container_name = f'zsequencer-node-{idx}'
        nodes_info[key_data.address] = simulations_utils.generate_node_info(
            node_idx=idx,
            key_data=key_data,
            node_host=container_name
        ).dict()

        # Update the environment variables to use container name instead of localhost
        env_vars = simulation_conf.to_dict(
            node_idx=idx,
            sequencer_initial_address=sequencer_address
        )
        # Update the host in ZSEQUENCER_HOST if it exists
        if 'ZSEQUENCER_HOST' in env_vars:
            env_vars['ZSEQUENCER_HOST'] = container_name

        nodes_execution_args[key_data.address] = ExecutionData(
            env_variables=env_vars
        )

    # Writing nodes info on host disk
    with open(simulation_conf.nodes_file, "w") as file:
        json.dump(nodes_info, file, indent=4)

    # Writing apps info on host disk
    with open(simulation_conf.apps_file, "w") as file:
        json.dump(simulations_utils.APPS, file, indent=4)

    # Start containers for each node
    sorted_ids = sorted(list(nodes_info.keys()))
    for idx, node_id in enumerate(sorted_ids):
        execution_data = nodes_execution_args[node_id]
        container_name = f"zsequencer-node-{idx}"

        # Remove container if it already exists
        subprocess.run(["docker", "rm", "-f", container_name],
                       capture_output=True)

        run_docker_container(
            image_name="zellular/zsequencer:latest",
            container_name=container_name,
            env_variables=execution_data.env_variables,
        )
        time.sleep(1)


if __name__ == "__main__":
    main()
