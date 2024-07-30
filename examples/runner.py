"""This script sets up and runs a simple app network for testing."""

import argparse
import json
import os
import secrets
import shutil
import subprocess
import time
from typing import Any

from eigensdk.crypto.bls import attestation
from web3 import Account

NUM_INSTANCES: int = 3
BASE_PORT: int = 6000
THRESHOLD_PERCENT: int = 60
DST_DIR: str = "/tmp/zellular_dev_net"
NODES_FILE: str = "/tmp/zellular_dev_net/nodes.json"
APPS_FILE: str = "/tmp/zellular_dev_net/apps.json"
ZSEQUENCER_SNAPSHOT_CHUNK: int = 1_000_000
ZSEQUENCER_REMOVE_CHUNK_BORDER: int = 3
ZSEQUENCER_SEND_TXS_INTERVAL: float = 0.01
ZSEQUENCER_SYNC_INTERVAL: float = 0.01
ZSEQUENCER_FINALIZATION_TIME_BORDER: int = 120
ZSEQUENCER_SIGNATURES_AGGREGATION_TIMEOUT = 10
APP_NAME: str = "simple_app"


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Run the specified test."
    )
    parser.add_argument(
        "--test",
        required=True,
        choices=["general", "throughput"],
        help="the test name.",
    )
    return parser.parse_args()


def generate_privates_and_nodes_info() -> tuple[list[str], dict[str, Any]]:
    """Generate private keys and nodes information for the network."""
    nodes_info_dict: dict[str, Any] = {}
    privates_list: list[str] = []
    for i in range(NUM_INSTANCES):
        private_key: str = secrets.token_hex(32)
        privates_list.append(private_key)
        key_pair: attestation.KeyPair = attestation.new_key_pair_from_string(
            private_key
        )
        address: str = Account().from_key(private_key).address
        nodes_info_dict[str(i + 1)] = {
            "id": str(i + 1),
            "public_key": key_pair.pub_g2.getStr(10).decode("utf-8"),
            "address": address,
            "host": "127.0.0.1",
            "port": str(BASE_PORT + i + 1),
            "stake": 10,
        }

    return privates_list, nodes_info_dict


def run_command(
    command_name: str, command_args: str, env_variables: dict[str, str]
) -> None:
    """Run a command in a new terminal tab."""
    script_dir: str = os.path.dirname(os.path.abspath(__file__))
    parent_dir: str = os.path.dirname(script_dir)
    os.chdir(parent_dir)

    command: str = f"python -u {command_name} {command_args}; echo; read -p 'Press enter to exit...'"
    launch_command: list[str] = ["gnome-terminal", "--tab", "--", "bash", "-c", command]
    with subprocess.Popen(args=launch_command, env=env_variables) as process:
        process.wait()


def main() -> None:
    """Main function to run the setup and launch nodes and run the test."""
    args: argparse.Namespace = parse_args()

    privates_list, nodes_info_dict = generate_privates_and_nodes_info()

    if not os.path.exists(DST_DIR):
        os.makedirs(DST_DIR)

    script_dir: str = os.path.dirname(os.path.abspath(__file__))
    parent_dir: str = os.path.dirname(script_dir)
    os.chdir(parent_dir)

    with open(file=NODES_FILE, mode="w", encoding="utf-8") as file:
        file.write(json.dumps(nodes_info_dict))

    with open(file=APPS_FILE, mode="w", encoding="utf-8") as file:
        file.write(json.dumps({f"{APP_NAME}": {"url": "", "public_keys": []}}))

    for i in range(NUM_INSTANCES):
        data_dir: str = f"{DST_DIR}/db_{i + 1}"
        try:
            shutil.rmtree(data_dir)
        except FileNotFoundError:
            pass

        # Create environment variables for a node instance
        environment_variables: dict[str, Any] = {
            "ZSEQUENCER_PORT": str(BASE_PORT + i + 1),
            "ZSEQUENCER_FLASK_SECRET_KEY": secrets.token_hex(24),
            "ZSEQUENCER_PUBLIC_KEY": nodes_info_dict[str(i + 1)]["public_key"],
            "ZSEQUENCER_PRIVATE_KEY": privates_list[i],
            "ZSEQUENCER_NODES_FILE": NODES_FILE,
            "ZSEQUENCER_APPS_FILE": APPS_FILE,
            "ZSEQUENCER_SNAPSHOT_CHUNK": str(ZSEQUENCER_SNAPSHOT_CHUNK),
            "ZSEQUENCER_REMOVE_CHUNK_BORDER": str(ZSEQUENCER_REMOVE_CHUNK_BORDER),
            "ZSEQUENCER_SNAPSHOT_PATH": data_dir,
            "ZSEQUENCER_THRESHOLD_PERCENT": str(THRESHOLD_PERCENT),
            "ZSEQUENCER_SEND_TXS_INTERVAL": str(ZSEQUENCER_SEND_TXS_INTERVAL),
            "ZSEQUENCER_SYNC_INTERVAL": str(ZSEQUENCER_SYNC_INTERVAL),
            "ZSEQUENCER_FINALIZATION_TIME_BORDER": str(
                ZSEQUENCER_FINALIZATION_TIME_BORDER),
            "ZSEQUENCER_SIGNATURES_AGGREGATION_TIMEOUT": str(
                ZSEQUENCER_SIGNATURES_AGGREGATION_TIMEOUT),
            "ZSEQUENCER_ENV_PATH": f"{DST_DIR}/node{i + 1}",
        }

        with open(
            file=f"{DST_DIR}/node{i + 1}.env", mode="w", encoding="utf-8"
        ) as file:
            for key, value in environment_variables.items():
                file.write(f"{key}={value}\n")

        env_variables: dict[str, str] = os.environ.copy()
        env_variables.update(environment_variables)

        run_command("run.py", f"{i + 1}", env_variables)
        time.sleep(2)

        if i == NUM_INSTANCES - 1:
            run_command(
                f"examples/{args.test}_test.py",
                f"--app_name {APP_NAME} --node_url http://localhost:{BASE_PORT + i + 1}",
                env_variables,
            )


if __name__ == "__main__":
    main()
