import hashlib
import json
import os
import secrets
import shutil
import subprocess
import time
from typing import Any, Dict, List

from fastecdsa import curve, keys
from fastecdsa.encoding.sec1 import SEC1Encoder
from web3 import Account

NUM_INSTANCES: int = 3
BASE_PORT: int = 6000
THRESHOLD_NUMBER: int = 2


def generate_privates_and_nodes_info() -> tuple[List[int], Dict[str, Any]]:
    previous_key: int = (
        71940701385098721223324549130922930535689437869965850741649618196713151413648
    )
    nodes_info_dict: Dict[str, Any] = {}
    privates_list: List[int] = []
    for i in range(NUM_INSTANCES):
        key_bytes: bytes = previous_key.to_bytes(32, "big")
        hashed: bytes = hashlib.sha256(key_bytes).digest()
        new_private: int = int.from_bytes(hashed, byteorder="big") % curve.secp256k1.q
        previous_key = new_private
        public_key: keys.Point = keys.get_public_key(new_private, curve.secp256k1)
        compressed_pub_key: int = int(
            SEC1Encoder.encode_public_key(public_key, True).hex(), 16
        )
        nodes_info_dict[str(i + 1)] = {
            "id": str(i + 1),
            "public_key": compressed_pub_key,
            "address": Account.from_key(new_private).address,
            "host": "127.0.0.1",
            "port": str(6000 + i + 1),
        }
        privates_list.append(new_private)
    return privates_list, nodes_info_dict


def run_command(command_name: str, command_args: str, env_variables: Dict[str, str]):
    script_dir: str = os.path.dirname(os.path.abspath(__file__))
    parent_dir: str = os.path.dirname(script_dir)
    os.chdir(parent_dir)

    command: str = (
        f"python {command_name} {command_args}; echo; read -p 'Press enter to exit...'"
    )
    launch_command: List[str] = ["gnome-terminal", "--tab", "--", "bash", "-c", command]
    subprocess.Popen(launch_command, env=env_variables)


def run():
    privates_list, nodes_info_dict = generate_privates_and_nodes_info()

    dst_dir: str = "/tmp/dev_net"
    if not os.path.exists(dst_dir):
        os.makedirs(dst_dir)

    script_dir: str = os.path.dirname(os.path.abspath(__file__))
    parent_dir: str = os.path.dirname(script_dir)
    os.chdir(parent_dir)

    with open("./nodes.json", "w") as f:
        f.write(json.dumps(nodes_info_dict))

    for i in range(NUM_INSTANCES):
        data_dir = f"./db__{i + 1}"
        try:
            shutil.rmtree(data_dir)
        except Exception:
            pass

        environment_variables: Dict[str, str] = {
            "ZSEQUENCER_PORT": str(BASE_PORT + i + 1),
            "ZSEQUENCER_SECRET_KEY": secrets.token_hex(24),
            "ZSEQUENCER_PUBLIC_KEY": str(nodes_info_dict[str(i + 1)]["public_key"]),
            "ZSEQUENCER_PRIVATE_KEY": str(privates_list[i]),
            "ZSEQUENCER_NODES_FILE": "./nodes.json",
            "ZSEQUENCER_SNAPSHOT_CHUNK": "200000",
            "ZSEQUENCER_REMOVE_CHUNK_BORDER": "3",
            "ZSEQUENCER_SNAPSHOT_PATH": data_dir,
            "ZSEQUENCER_THRESHOLD_NUMBER": str(THRESHOLD_NUMBER),
            "ZSEQUENCER_SEND_TXS_INTERVAL": "0.1",
            "ZSEQUENCER_SYNC_INTERVAL": "0.1",
            "ZSEQUENCER_MIN_NONCES": "10",
            "ZSEQUENCER_FINALIZATION_TIME_BORDER": "120",
            "ZSEQUENCER_ENV_PATH": f"{dst_dir}/node{i + 1}",
        }

        with open(f"{dst_dir}/node{i + 1}.env", "w") as f:
            for key, value in environment_variables.items():
                f.write(f"{key}={value}\n")

        env_variables = os.environ.copy()
        env_variables.update(environment_variables)

        run_command("run.py", f"{i + 1}", env_variables)
        time.sleep(2)
        if i == 2:
            run_command("examples/init_network.py", "", env_variables)
            time.sleep(1)
            run_command("examples/simple_app.py", "", env_variables)


if __name__ == "__main__":
    run()
