"""This script sets up and runs a simple app network for testing."""

import hashlib
import json
import os
import secrets
import shutil
import subprocess
import time
from typing import Any

from fastecdsa import curve, keys
from fastecdsa.encoding.sec1 import SEC1Encoder
from web3 import Account

NUM_INSTANCES: int = 3
BASE_PORT: int = 6000
THRESHOLD_NUMBER: int = 2
DST_DIR: str = "/tmp/zellular_dev_net"
NODES_FILE: str = "/tmp/zellular_dev_net/nodes.json"
APPS_FILE: str = "/tmp/zellular_dev_net/apps.json"
BATCH_SIZE: int = 100_000
BATCH_NUMBER: int = 1
APP_NAME: str = "simple_app"


def generate_privates_and_nodes_info() -> tuple[list[int], dict[str, Any]]:
    """Generate private keys and nodes information for the network."""
    previous_key: int = (
        71940701385098721223324549130922930535689437869965850741649618196713151413648
    )
    nodes_info_dict: dict[str, Any] = {}
    privates_list: list[int] = []
    for i in range(NUM_INSTANCES):
        key_bytes: bytes = previous_key.to_bytes(32, "big")
        hashed: bytes = hashlib.sha256(key_bytes).digest()
        new_private: int = int.from_bytes(hashed, byteorder="big") % curve.secp256k1.q
        previous_key = new_private
        public_key: keys.Point = keys.get_public_key(new_private, curve.secp256k1)
        compressed_pub_key: int = int(
            SEC1Encoder.encode_public_key(public_key, True).hex(), 16
        )
        address: str = Account().from_key(new_private).address
        nodes_info_dict[str(i + 1)] = {
            "id": str(i + 1),
            "public_key": compressed_pub_key,
            "address": address,
            "host": "127.0.0.1",
            "port": str(BASE_PORT + i + 1),
        }
        privates_list.append(new_private)
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
        environment_variables: dict[str, str] = {
            "ZSEQUENCER_PORT": str(BASE_PORT + i + 1),
            "ZSEQUENCER_SECRET_KEY": secrets.token_hex(24),
            "ZSEQUENCER_PUBLIC_KEY": str(nodes_info_dict[str(i + 1)]["public_key"]),
            "ZSEQUENCER_PRIVATE_KEY": str(privates_list[i]),
            "ZSEQUENCER_NODES_FILE": NODES_FILE,
            "ZSEQUENCER_APPS_FILE": APPS_FILE,
            "ZSEQUENCER_SNAPSHOT_CHUNK": "10000000",
            "ZSEQUENCER_REMOVE_CHUNK_BORDER": "3",
            "ZSEQUENCER_SNAPSHOT_PATH": data_dir,
            "ZSEQUENCER_THRESHOLD_NUMBER": str(THRESHOLD_NUMBER),
            "ZSEQUENCER_SEND_TXS_INTERVAL": "0.1",
            "ZSEQUENCER_SYNC_INTERVAL": "0.1",
            "ZSEQUENCER_MIN_NONCES": "10",
            "ZSEQUENCER_FINALIZATION_TIME_BORDER": "120",
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
            run_command("examples/init_network.py", "", env_variables)
            time.sleep(2)
            run_command(
                "examples/simple_app.py",
                f"--batch_size {BATCH_SIZE} --batch_number {BATCH_NUMBER} --app_name {APP_NAME} --node_url http://localhost:{BASE_PORT + i + 1}",
                env_variables,
            )


if __name__ == "__main__":
    main()
