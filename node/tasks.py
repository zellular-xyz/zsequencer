"""
This module handles node tasks like sending transactions, synchronization with the sequencer,
dispute handling, and switching sequencers.
"""

import json
import threading
import time
from typing import Any

import requests

from zsequencer.common import utils
from zsequencer.common.db import zdb
from zsequencer.common.logger import zlogger
from zsequencer.config import zconfig

switch_lock: threading.Lock = threading.Lock()


def check_finalization() -> None:
    """Check and add not finalized transactions to missed transactions."""
    for app_name in zconfig.APPS.keys():
        not_finalized_txs: dict[str, Any] = zdb.get_not_finalized_txs(app_name)
        if not_finalized_txs:
            zdb.add_missed_txs(app_name=app_name, txs=not_finalized_txs)


def send_txs() -> None:
    """Send transactions for all apps."""
    for app_name in zconfig.APPS:
        send_app_txs(app_name)


def send_app_txs(app_name: str) -> None:
    """Send transactions for a specific app."""
    initialized_txs: dict[str, Any] = zdb.get_txs(
        app_name=app_name, states={"initialized"}
    )

    last_synced_tx: dict[str, Any] = zdb.get_last_tx(
        app_name=app_name, state="sequenced"
    )
    last_locked_tx: dict[str, Any] = zdb.get_last_tx(app_name=app_name, state="locked")

    concat_hash: str = "".join(initialized_txs.keys())
    concat_sig: str = utils.sign(msg=concat_hash)

    data: str = json.dumps(
        {
            "app_name": app_name,
            "txs": list(initialized_txs.values()),
            "node_id": zconfig.NODE["id"],
            "sig": concat_sig,
            "sequenced_index": last_synced_tx.get("index", 0),
            "sequenced_hash": last_synced_tx.get("hash", ""),
            "sequenced_chaining_hash": last_synced_tx.get("chaining_hash", ""),
            "locked_index": last_locked_tx.get("index", 0),
            "locked_hash": last_locked_tx.get("hash", ""),
            "locked_chaining_hash": last_locked_tx.get("chaining_hash", ""),
            "timestamp": int(time.time()),
        }
    )

    sequencer_address: str = f'{zconfig.SEQUENCER["host"]}:{zconfig.SEQUENCER["port"]}'
    url: str = f"http://{sequencer_address}/sequencer/transactions"
    try:
        response: dict[str, Any] = requests.put(
            url=url, data=data, headers=zconfig.HEADERS
        ).json()
        if response["status"] == "error":
            zdb.add_missed_txs(app_name=app_name, txs=initialized_txs)
            return

        sync_with_sequencer(
            app_name=app_name,
            initialized_txs=initialized_txs,
            sequencer_response=response["data"],
        )
    except Exception:
        zlogger.exception("An error occurred:")
        zdb.add_missed_txs(app_name=app_name, txs=initialized_txs)

    check_finalization()


def sync_with_sequencer(
    app_name: str, initialized_txs: dict[str, Any], sequencer_response: dict[str, Any]
) -> None:
    """Sync transactions with the sequencer."""
    if sequencer_response["locked"]["index"]:
        if not utils.is_frost_sig_verified(
            sig=sequencer_response["locked"]["sig"],
            index=sequencer_response["locked"]["index"],
            chaining_hash=sequencer_response["locked"]["chaining_hash"],
        ):
            return

        zdb.update_locked_txs(
            app_name=app_name,
            sig_data=sequencer_response["locked"],
        )

    if sequencer_response["finalized"]["index"]:
        if not utils.is_frost_sig_verified(
            sig=sequencer_response["finalized"]["sig"],
            index=sequencer_response["finalized"]["index"],
            chaining_hash=sequencer_response["finalized"]["chaining_hash"],
        ):
            return

        zdb.update_finalized_txs(
            app_name=app_name,
            sig_data=sequencer_response["finalized"],
        )

    zdb.upsert_sequenced_txs(app_name=app_name, txs=sequencer_response["txs"])
    check_censorship(
        app_name=app_name,
        initialized_txs=initialized_txs,
        sequencer_response=sequencer_response,
    )


def check_censorship(
    app_name: str, initialized_txs: dict[str, Any], sequencer_response: dict[str, Any]
) -> None:
    """Check for censorship by comparing initialized and sequenced transactions."""
    synced_hashes: set[str] = set(tx["hash"] for tx in sequencer_response["txs"])
    initialized_hashes: set[str] = set(initialized_txs.keys())
    censored_hashes: set[str] = initialized_hashes - synced_hashes
    censored_txs: dict[str, Any] = {
        _hash: initialized_txs[_hash] for _hash in censored_hashes
    }

    current_missed_hashes: set[str] = set(zdb.get_missed_txs(app_name).keys())
    new_missed_hashes: set[str] = current_missed_hashes - synced_hashes
    new_missed_txs: dict[str, Any] = {
        _hash: zdb.get_missed_txs(app_name)[_hash] for _hash in new_missed_hashes
    }
    new_missed_txs.update(censored_txs)

    zdb.set_missed_txs(app_name=app_name, txs=new_missed_txs)


def send_dispute_requests() -> None:
    """Send dispute requests if there are missed transactions."""
    if not zdb.has_missed_txs():
        return

    timestamp: int = int(time.time())
    new_sequencer_id: str = utils.get_next_sequencer_id(
        old_sequencer_id=zconfig.SEQUENCER["id"]
    )
    proofs: list[dict[str, Any]] = [
        {
            "node_id": zconfig.NODE["id"],
            "old_sequencer_id": zconfig.SEQUENCER["id"],
            "new_sequencer_id": new_sequencer_id,
            "timestamp": timestamp,
            "sig": utils.sign(f'{zconfig.SEQUENCER["id"]}{timestamp}'),
        }
    ]

    missed_txs_by_app: dict[str, dict[str, Any]] = get_missed_transactions_by_app()

    for node in zconfig.NODES.values():
        if node["id"] in {zconfig.NODE["id"], zconfig.SEQUENCER["id"]}:
            continue

        for app_name, missed_txs in missed_txs_by_app.items():
            try:
                response: dict[str, Any] = send_dispute_request(
                    node, app_name, missed_txs
                )
                if response["status"] == "success":
                    proofs.append(response["data"])
            except Exception:
                zlogger.exception("An error occurred:")

    if utils.is_switch_approved(proofs):
        send_switch_requests(proofs=proofs)
        switch_sequencer(proofs=proofs, _type="SELF")


def get_missed_transactions_by_app() -> dict[str, Any]:
    """Get missed transactions for all apps."""
    missed_txs_by_app: dict[str, Any] = {}
    for app_name in zconfig.APPS.keys():
        missed_txs: dict[str, Any] = zdb.get_missed_txs(app_name)
        if missed_txs:
            missed_txs_by_app[app_name] = missed_txs
    return missed_txs_by_app


def send_dispute_request(
    node: dict[str, Any], app_name: str, missed_txs: dict[str, Any]
) -> dict[str, Any]:
    """Send a dispute request to a specific node."""
    timestamp: int = int(time.time())
    data: str = json.dumps(
        {
            "sequencer_id": zconfig.SEQUENCER["id"],
            "app_name": app_name,
            "txs": missed_txs,
            "timestamp": timestamp,
        }
    )
    url: str = f'http://{node["host"]}:{node["port"]}/node/dispute'
    return requests.post(url=url, data=data, headers=zconfig.HEADERS).json()


def send_switch_requests(proofs: list[dict[str, Any]]) -> None:
    """Send switch requests to all nodes except self."""
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
        try:
            requests.post(url=url, data=data, headers=zconfig.HEADERS).json()
        except Exception:
            zlogger.exception("An error occurred:")


def switch_sequencer(proofs: list[dict[str, Any]], _type: str) -> bool:
    """Switch the sequencer if the proofs are approved."""
    with switch_lock:
        old_sequencer_id, new_sequencer_id = utils.get_switch_parameter_from_proofs(
            proofs=proofs
        )

        if not utils.is_switch_approved(proofs=proofs):
            return False

        zdb.pause_node.set()
        assert old_sequencer_id == zconfig.SEQUENCER["id"], "something went wrong"

        zconfig.update_sequencer(new_sequencer_id)
        assert new_sequencer_id == zconfig.SEQUENCER["id"], "something went wrong"

        for app_name in zconfig.APPS.keys():
            zdb.empty_missed_txs(app_name)
            last_finalized_tx: dict[str, Any] = get_last_finalized_tx(app_name)
            zdb.update_finalized_txs(
                app_name=app_name,
                sig_data=last_finalized_tx,
            )

            if zconfig.NODE["id"] == new_sequencer_id:
                zdb.resequence_txs(
                    app_name=app_name, last_finalized_tx=last_finalized_tx
                )
                time.sleep(30)
            else:
                zdb.update_reinitialized_txs(
                    app_name=app_name, last_finalized_tx=last_finalized_tx["index"]
                )
                time.sleep(60)

        zdb.pause_node.clear()
        return zconfig.SEQUENCER["id"] == new_sequencer_id


def get_last_finalized_tx(app_name: str) -> dict[str, Any]:
    """Get the last finalized transaction from all nodes."""
    last_finalized_tx: dict[str, Any] = zdb.get_last_tx(
        app_name=app_name, state="finalized"
    )

    for node in zconfig.NODES.values():
        if node["id"] == zconfig.NODE["id"]:
            continue

        node_address: str = f'http://{node["host"]}:{node["port"]}'
        url: str = f"http://{node_address}/node/{app_name}/transactions/finalized/last"
        try:
            response: dict[str, Any] = requests.get(
                url=url, headers=zconfig.HEADERS
            ).json()
            tx: dict[str, Any] = response.get("data", {})
            if tx.get("index", 0) > last_finalized_tx.get("index", 0):
                last_finalized_tx = tx
        except Exception:
            zlogger.exception("An error occurred:")

    return last_finalized_tx
