import json
import threading
import time
from typing import Any, Dict, List

import requests

import config
from shared_state import state

from ..common import db, utils
from ..common.logger import zellular_logger
from ..sequencer import tasks as sequencer_tasks

switch_lock: threading.Lock = threading.Lock()


def init_tx(tx: Dict[str, Any]) -> bool:
    if config.NODE["id"] == config.SEQUENCER["id"]:
        return False

    db.insert_tx(tx)
    return True


def get_finalized(after: int) -> List[Dict[str, Any]]:
    query: Dict[str, Any] = {"index": {"$gt": after}, "state": "finalized"}
    cursor = db.txs_col.find(query)
    return list(cursor)


def check_finalization() -> None:
    not_finalized_txs: Dict[str, Any] = db.get_not_finalized_txs()
    if not_finalized_txs:
        state.add_missed_txs(not_finalized_txs)


def send_txs() -> None:
    initialized_txs: Dict[str, Any] = db.get_initialized_txs()

    last_synced_tx: Dict[str, Any] = db.get_last_synced_tx() or {}

    concat_hash: str = "".join(initialized_txs.keys())
    concat_sig: str = utils.sign(concat_hash)

    data: str = json.dumps(
        {
            "txs": list(initialized_txs.values()),
            "node_id": config.NODE["id"],
            "index": last_synced_tx.get("index", 0),
            "chaining_hash": last_synced_tx.get("chaining_hash", ""),
            "sig": concat_sig,
            "timestamp": int(time.time()),
        }
    )
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    url: str = f'http://{config.SEQUENCER["host"]}:{config.SEQUENCER["server_port"]}/sequencer/transactions'
    try:
        response: Dict[str, Any] = requests.put(url, data, headers=headers).json()
        if response["status"] == "error":
            state.add_missed_txs(initialized_txs)
            return

        sync_with_sequencer(initialized_txs, response["data"])
    except Exception:
        zellular_logger.exception("An error occurred:")
        state.add_missed_txs(initialized_txs)

    check_finalization()


def sync_with_sequencer(
    initialized_txs: Dict[str, Any], sequencer_response: Dict[str, Any]
) -> None:
    synced_hashes: List[str] = [db.gen_tx_hash(tx) for tx in sequencer_response["txs"]]

    censored_txs: Dict[str, Any] = {
        k: v for k, v in initialized_txs.items() if k not in synced_hashes
    }

    # remove synced txs from missed_txs
    state.set_missed_txs(
        {k: v for k, v in state.get_missed_txs().items() if k not in synced_hashes}
    )
    state.add_missed_txs(censored_txs)

    if sequencer_response["finalized"]["index"]:
        if not utils.is_frost_sig_verified(
            sequencer_response["finalized"]["sig"],
            sequencer_response["finalized"]["index"],
            sequencer_response["finalized"]["chaining_hash"],
        ):
            return

    db.upsert_sequenced_txs(sequencer_response["txs"])
    db.update_finalized_txs(sequencer_response["finalized"]["index"])


def send_dispute_requests() -> None:
    if not state.get_missed_txs_number():
        return

    zellular_logger.info("sending dispute requests...")
    timestamp: int = int(time.time())
    new_sequencer_id: str = utils.get_next_sequencer_id(config.SEQUENCER["id"])
    proofs: List[Dict[str, Any]] = [
        {
            "node_id": config.NODE["id"],
            "old_sequencer_id": config.SEQUENCER["id"],
            "new_sequencer_id": new_sequencer_id,
            "timestamp": timestamp,
            "sig": utils.sign(f'{config.SEQUENCER["id"]}{timestamp}'),
        }
    ]
    for node in config.NODES.values():
        if node["id"] in [config.NODE["id"], config.SEQUENCER["id"]]:
            continue

        try:
            response: Dict[str, Any] = send_dispute_request(node)
            if response["status"] == "success":
                proofs.append(response["data"])
        except Exception:
            zellular_logger.exception("An error occurred:")

    if utils.is_switch_approved(proofs):
        send_switch_requests(proofs)
        switch_sequencer(proofs, "SELF")

    # TODO: make sure all the nodes switched?!


def send_dispute_request(node: Dict[str, Any]) -> Dict[str, Any]:
    timestamp: int = int(time.time())
    data: str = json.dumps(
        {
            "sequencer_id": config.SEQUENCER["id"],
            "txs": list(state.get_missed_txs().values()),
            "timestamp": timestamp,
        }
    )
    url: str = f'http://{node["host"]}:{node["server_port"]}/node/dispute'
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    return requests.post(url, data, headers=headers).json()


def send_switch_requests(proofs: List[Dict[str, Any]]) -> None:
    zellular_logger.info("sending switch requests...")
    for node in config.NODES.values():
        if node["id"] == config.NODE["id"]:
            continue

        data: str = json.dumps(
            {
                "proofs": proofs,
                "timestamp": int(time.time()),
            }
        )
        url: str = f'http://{node["host"]}:{node["server_port"]}/node/sequencer/switch'
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        try:
            requests.post(url, data, headers=headers).json()
        except Exception:
            zellular_logger.exception("An error occurred:")


def switch_sequencer(proofs: List[Dict[str, Any]], _type: str) -> bool:
    with switch_lock:
        old_sequencer_id, new_sequencer_id = utils.get_switch_parameter_from_proofs(
            proofs
        )

        if not utils.is_switch_approved(proofs):
            return False

        zellular_logger.info("switching the sequencer...")
        state._pause_node.set()
        assert old_sequencer_id == config.SEQUENCER["id"], "something went wrong"
        config.update_sequencer(new_sequencer_id)
        assert new_sequencer_id == config.SEQUENCER["id"], "something went wrong"
        state.empty_missed_txs()
        if config.NODE["id"] == new_sequencer_id:
            switch_to_sequencer()
            time.sleep(30)
        else:
            db.reinitialize_txs()
            time.sleep(60)

        state._pause_node.clear()
        return config.SEQUENCER["id"] == new_sequencer_id


def switch_to_sequencer() -> None:
    last_finalized_tx: Dict[str, Any] = sequencer_tasks.get_last_finalized_tx()
    db.update_to_sequencer(last_finalized_tx)
