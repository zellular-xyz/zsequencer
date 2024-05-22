import json
import os
import threading
import time
from collections import Counter
from typing import Any, Dict, List, Optional, Set

import requests

from config import zconfig
from shared_state import state

from ..common import utils
from ..common.db import zdb
from ..common.logger import zlogger

switch_lock: threading.Lock = threading.Lock()


def check_finalization() -> None:
    not_finalized_txs: Dict[str, Any] = zdb.get_not_finalized_txs()
    if not_finalized_txs:
        state.add_missed_txs(not_finalized_txs)


def send_txs() -> None:
    initialized_txs: Dict[str, Any] = zdb.get_txs(states=["initialized"])

    last_synced_tx: Dict[str, Any] = (
        zdb.last_sequenced_tx or zdb.last_finalized_tx or {}
    )

    concat_hash: str = "".join(initialized_txs.keys())
    concat_sig: str = utils.sign(concat_hash)

    data: str = json.dumps(
        {
            "txs": list(initialized_txs.values()),
            "node_id": zconfig.NODE["id"],
            "index": last_synced_tx.get("index", 0),
            "chaining_hash": last_synced_tx.get("chaining_hash", ""),
            "hash": last_synced_tx.get("hash", ""),
            "sig": concat_sig,
            "timestamp": int(time.time()),
        }
    )

    headers: Dict[str, str] = {"Content-Type": "application/json"}
    url: str = f'http://{zconfig.SEQUENCER["host"]}:{zconfig.SEQUENCER["port"]}/sequencer/transactions'
    try:
        response: Dict[str, Any] = requests.put(url, data, headers=headers).json()
        if response["status"] == "error":
            state.add_missed_txs(initialized_txs)
            return

        sync_with_sequencer(initialized_txs, response["data"])
    except Exception:
        zlogger.exception("An error occurred:")
        state.add_missed_txs(initialized_txs)

    check_finalization()


def sync_with_sequencer(
    initialized_txs: Dict[str, Any], sequencer_response: Dict[str, Any]
) -> None:
    if sequencer_response["finalized"]["index"]:
        if not utils.is_frost_sig_verified(
            sequencer_response["finalized"]["sig"],
            sequencer_response["finalized"]["index"],
            sequencer_response["finalized"]["chaining_hash"],
        ):
            return

    synced_hashes: Set[str] = set(tx["hash"] for tx in sequencer_response["txs"])
    initialized_hashes: Set[str] = set(initialized_txs.keys())
    current_missed_hashes: Set[str] = set(state.get_missed_txs().keys())

    censored_hashes: Set[str] = initialized_hashes - synced_hashes
    censored_txs: Dict[str, Any] = {
        hash_: initialized_txs[hash_] for hash_ in censored_hashes
    }

    new_missed_hashes: Set[str] = current_missed_hashes - synced_hashes
    new_missed_txs: Dict[str, Any] = {
        hash_: state.get_missed_txs()[hash_] for hash_ in new_missed_hashes
    }
    new_missed_txs.update(censored_txs)

    state.set_missed_txs(new_missed_txs)

    zdb.upsert_sequenced_txs(sequencer_response["txs"])
    if sequencer_response["finalized"]["index"]:
        zdb.update_finalized_txs(sequencer_response["finalized"]["index"])
        zdb.insert_sync_sig(sequencer_response["finalized"])


def send_dispute_requests() -> None:
    if not state.get_missed_txs_number():
        return

    timestamp: int = int(time.time())
    new_sequencer_id: str = utils.get_next_sequencer_id(zconfig.SEQUENCER["id"])
    proofs: List[Dict[str, Any]] = [
        {
            "node_id": zconfig.NODE["id"],
            "old_sequencer_id": zconfig.SEQUENCER["id"],
            "new_sequencer_id": new_sequencer_id,
            "timestamp": timestamp,
            "sig": utils.sign(f'{zconfig.SEQUENCER["id"]}{timestamp}'),
        }
    ]
    for node in zconfig.NODES.values():
        if node["id"] in [zconfig.NODE["id"], zconfig.SEQUENCER["id"]]:
            continue

        try:
            response: Dict[str, Any] = send_dispute_request(node)
            if response["status"] == "success":
                proofs.append(response["data"])
        except Exception:
            zlogger.exception("An error occurred:")

    if utils.is_switch_approved(proofs):
        send_switch_requests(proofs)
        switch_sequencer(proofs, "SELF")

    # TODO: make sure all the nodes switched?!


def send_dispute_request(node: Dict[str, Any]) -> Dict[str, Any]:
    timestamp: int = int(time.time())
    data: str = json.dumps(
        {
            "sequencer_id": zconfig.SEQUENCER["id"],
            "txs": [tx["body"] for tx in state.get_missed_txs().values()],
            "timestamp": timestamp,
        }
    )
    url: str = f'http://{node["host"]}:{node["port"]}/node/dispute'
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    return requests.post(url, data, headers=headers).json()


def send_switch_requests(proofs: List[Dict[str, Any]]) -> None:
    zlogger.info("sending switch requests...")
    for node in zconfig.NODES.values():
        if node["id"] == zconfig.NODE["id"]:
            continue

        data: str = json.dumps(
            {
                "proofs": proofs,
                "timestamp": int(time.time()),
            }
        )
        url: str = f'http://{node["host"]}:{node["port"]}/node/switch'
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        try:
            requests.post(url, data, headers=headers).json()
        except Exception:
            zlogger.exception("An error occurred:")


def switch_sequencer(proofs: List[Dict[str, Any]], _type: str) -> bool:
    with switch_lock:
        old_sequencer_id, new_sequencer_id = utils.get_switch_parameter_from_proofs(
            proofs
        )

        if not utils.is_switch_approved(proofs):
            return False
        state._pause_node.set()
        assert old_sequencer_id == zconfig.SEQUENCER["id"], "something went wrong"
        zconfig.update_sequencer(new_sequencer_id)
        assert new_sequencer_id == zconfig.SEQUENCER["id"], "something went wrong"
        state.empty_missed_txs()
        last_finalized_tx: Dict[str, Any] = get_last_finalized_tx()
        zdb.update_finalized_txs(last_finalized_tx["index"])

        if zconfig.NODE["id"] == new_sequencer_id:
            zdb.resequence_txs(last_finalized_tx)
            time.sleep(30)
        else:
            zdb.update_reinitialized_txs(last_finalized_tx["index"])
            time.sleep(60)

        state._pause_node.clear()
        return zconfig.SEQUENCER["id"] == new_sequencer_id


def get_last_finalized_tx() -> Dict[str, Any]:
    last_finalized_tx: Dict[str, Any] = zdb.last_finalized_tx or {
        "index": 0,
        "chaining_hash": "",
    }

    for node in zconfig.NODES.values():
        if node["id"] == zconfig.NODE["id"]:
            continue

        url: str = (
            f'http://{node["host"]}:{node["port"]}/node/finalized_transactions/last'
        )
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        try:
            response: requests.Response = requests.get(url, headers=headers)
            resp: Dict[str, Any] = response.json()
            tx: Dict[str, Any] = resp.get("data", {})
            if tx.get("index", 0) > last_finalized_tx["index"]:
                last_finalized_tx = tx

        except Exception:
            zlogger.exception("An error occurred:")

    return last_finalized_tx


def get_network_data_state() -> Dict[str, Any]:
    data_states: List[Dict[str, Any]] = []
    node_ids: List[str] = []
    result: Dict[str, Any] = {}

    for node in zconfig.NODES.values():
        if node["id"] in [zconfig.NODE["id"], zconfig.SEQUENCER["id"]]:
            continue

        data_state: Optional[Dict[str, Any]] = get_node_data_state(node)
        if not data_state:
            continue

        data_states.append(data_state)

    hashes = [d["hash"] for d in data_states if "hash" in d]
    hash_counts = Counter(hashes)
    if not hash_counts:
        return result

    most_common: tuple = hash_counts.most_common(1)[0]
    if most_common[1] < zconfig.THRESHOLD_NUMBER:
        return result

    for data_state in data_states:
        zdb.upsert_node_data_state(node["id"], data_state)
        if data_state["hash"] != most_common[0]:
            continue

        node_ids.append(node["id"])
        if not result and data_state["files"]:
            result = data_state

    result["node_ids"] = node_ids
    zdb.upsert_network_data_state(result)
    return result


def get_node_data_state(node: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    url: str = f'http://{node["host"]}:{node["port"]}/node/data_state'
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    try:
        response: Dict[str, Any] = requests.get(url, headers=headers).json()
        if response["status"] != "success":
            return

        if not utils.is_sig_verified(
            response["data"]["signature"], node["id"], response["data"]["hash"]
        ):
            return

        return response["data"]
    except Exception:
        zlogger.exception("An error occurred:")


def get_local_data_file(file_name: str) -> Optional[str]:
    data_state: Dict[str, Any] = zdb.get_node_data_state(zconfig.NODE["id"]) or {}
    file_path: str = data_state.get("files", {}).get(file_name)
    if not file_path or not os.path.exists(file_path):
        return

    with open(file_path, "r") as f:
        return f.read()


def get_remote_data_file(file_name: str) -> Optional[str]:
    network_data_state: Optional[Dict[str, Any]] = zdb.get_network_data_state()
    if not network_data_state:
        return

    for node_id in network_data_state["node_ids"]:
        data_state: Dict[str, Any] = zdb.get_node_data_state(node_id) or {}
        if file_name not in data_state.get("files", {}):
            continue

        node: Dict[str, Any] = zconfig.NODES[node_id]
        url: str = (
            f'http://{node["host"]}:{node["port"]}/node/data_state/files/{file_name}'
        )
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        try:
            response: Dict[str, Any] = requests.get(url, headers=headers).json()
            if response["status"] == "success":
                return response["data"]
        except Exception:
            zlogger.exception("An error occurred:")
