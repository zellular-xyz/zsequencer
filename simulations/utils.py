"""This script sets up and runs a simple app network for testing."""
import json
import os
import secrets
import shutil
from typing import Dict, List, Tuple
from uuid import uuid4

from eigensdk.crypto.bls import attestation
from web3 import Account

from simulations.config import Keys, KeyData, NodeInfo, BASE_NODE_PORT


def generate_keys() -> Keys:
    bls_private_key: str = secrets.token_hex(32)
    bls_key_pair: attestation.KeyPair = attestation.new_key_pair_from_string(bls_private_key)
    ecdsa_private_key: str = secrets.token_hex(32)

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


def prepare_simulation_directory(simulation_conf):
    for filename in os.listdir(simulation_conf.DST_DIR):
        file_path = os.path.join(simulation_conf.DST_DIR, filename)
        if os.path.isfile(file_path):
            os.remove(file_path)

    with open(os.path.join(simulation_conf.DST_DIR, 'apps.json'), "w") as file:
        json.dump(simulation_conf.APPS, file, indent=4)


def remove_directory(path: str) -> None:
    """
    Remove a directory and its contents using shutil.

    Args:
        path: Path to the directory to remove.
    """
    if not os.path.exists(path):
        print(f"Directory '{path}' does not exist.")
        return

    if not os.path.isdir(path):
        print(f"'{path}' is not a directory.")
        return

    try:
        shutil.rmtree(path)
        print(f"Successfully removed '{path}' and its contents.")
    except Exception as e:
        print(f"Error removing directory '{path}': {e}")


def clean_directory_except_db(path: str) -> None:
    """
    Remove all contents of a directory except subdirectories starting with 'db_'.

    Args:
        path: Path to the directory to clean.
    """
    if not os.path.exists(path):
        print(f"Directory '{path}' does not exist.")
        return

    if not os.path.isdir(path):
        print(f"'{path}' is not a directory.")
        return

    for item in os.listdir(path):
        item_path = os.path.join(path, item)

        # Skip subdirectories that start with 'db_'
        if os.path.isdir(item_path) and item.startswith("db_"):
            continue

        try:
            if os.path.isdir(item_path):
                shutil.rmtree(item_path)
            else:
                os.remove(item_path)
            print(f"Removed: {item_path}")
        except Exception as e:
            print(f"Error removing '{item_path}': {e}")


def generate_transactions(batch_size: int) -> List[Dict]:
    return [
        {
            "operation": "foo",
            "serial": str(uuid4()),
            "version": 6,
        } for _ in range(batch_size)
    ]


APPS = {
    "simple_app": {
        "url": "",
        "public_keys": []
    }
}
