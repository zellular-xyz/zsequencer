"""
This module handles node tasks like sending transactions, synchronization with the sequencer,
dispute handling, and switching sequencers.
"""

import json
import threading
import time
from typing import Any

import requests
from eigensdk.crypto.bls import attestation

from zsequencer.common import bls, utils
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
    zdb.is_sequencer_down = False


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
    concat_sig: str = utils.eth_sign(concat_hash)

    data: str = json.dumps(
        {
            "app_name": app_name,
            "txs": list(initialized_txs.values()),
            "node_id": zconfig.NODE["id"],
            "signature": concat_sig,
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
        zlogger.exception("An unexpected error occurred:")
        zdb.add_missed_txs(app_name=app_name, txs=initialized_txs)
        zdb.is_sequencer_down = True

    check_finalization()


def sync_with_sequencer(
    app_name: str, initialized_txs: dict[str, Any], sequencer_response: dict[str, Any]
) -> None:
    """Sync transactions with the sequencer."""
    zdb.upsert_sequenced_txs(app_name=app_name, txs=sequencer_response["txs"])

    if sequencer_response["locked"]["index"]:
        if is_sync_point_signature_verified(
            app_name=app_name,
            state="sequenced",
            index=sequencer_response["locked"]["index"],
            tx_hash=sequencer_response["locked"]["hash"],
            chaining_hash=sequencer_response["locked"]["chaining_hash"],
            signature_hex=sequencer_response["locked"]["signature"],
            nonsigners=sequencer_response["locked"]["nonsigners"],
        ):
            zdb.update_locked_txs(
                app_name=app_name,
                sig_data=sequencer_response["locked"],
            )

    if sequencer_response["finalized"]["index"]:
        if is_sync_point_signature_verified(
            app_name=app_name,
            state="locked",
            index=sequencer_response["finalized"]["index"],
            tx_hash=sequencer_response["finalized"]["hash"],
            chaining_hash=sequencer_response["finalized"]["chaining_hash"],
            signature_hex=sequencer_response["finalized"]["signature"],
            nonsigners=sequencer_response["finalized"]["nonsigners"],
        ):
            zdb.update_finalized_txs(
                app_name=app_name,
                sig_data=sequencer_response["finalized"],
            )

    check_censorship(
        app_name=app_name,
        initialized_txs=initialized_txs,
        sequencer_response=sequencer_response,
    )


def check_censorship(
    app_name: str, initialized_txs: dict[str, Any], sequencer_response: dict[str, Any]
) -> None:
    """Check for censorship and update missed transactions."""
    sequenced_hashes: set[str] = set(tx["hash"] for tx in sequencer_response["txs"])
    censored_txs: dict[str, Any] = {
        tx_hash: tx
        for tx_hash, tx in initialized_txs.items()
        if tx_hash not in sequenced_hashes
    }

    # remove sequenced transactions from the missed transactions dict
    missed_txs: dict[str, Any] = {
        tx_hash: tx
        for tx_hash, tx in list(zdb.get_missed_txs(app_name).items())
        if tx_hash not in sequenced_hashes
    }

    # add censored transactions to the missed transactions dict
    missed_txs.update(censored_txs)

    zdb.set_missed_txs(app_name=app_name, txs=missed_txs)


def sign_sync_point(sync_point: dict[str, Any]) -> str:
    """confirm and sign the sync point"""
    tx: dict[str, Any] = zdb.get_tx(sync_point["app_name"], sync_point["hash"])
    for key in ["app_name", "state", "index", "hash", "chaining_hash"]:
        if tx.get(key) != sync_point[key]:
            return ""
    message: str = utils.gen_hash(json.dumps(sync_point, sort_keys=True))
    signature = bls.bls_sign(message)
    return signature


def is_sync_point_signature_verified(
    app_name: str,
    state: str,
    index: int,
    tx_hash: str,
    chaining_hash: str,
    signature_hex: str,
    nonsigners: list[str],
) -> bool:
    """Verify the BLS signature of a synchronization point."""
    public_key: attestation.G2Point = bls.get_signers_aggregated_public_key(nonsigners)
    message: str = utils.gen_hash(
        json.dumps(
            {
                "app_name": app_name,
                "state": state,
                "index": index,
                "hash": tx_hash,
                "chaining_hash": chaining_hash,
            },
            sort_keys=True,
        )
    )
    return bls.is_bls_sig_verified(
        signature_hex=signature_hex,
        message=message,
        public_key=public_key,
    )


def send_dispute_requests() -> None:
    """Send dispute requests if there are missed transactions."""
    if (not zdb.has_missed_txs() and not zdb.is_sequencer_down) or zdb.pause_node.is_set():
        return

    timestamp: int = int(time.time())
    new_sequencer_id: str = utils.get_next_sequencer_id(
        old_sequencer_id=zconfig.SEQUENCER["id"]
    )
    proofs: list[dict[str, Any]] = []
    proofs.append(
        {
            "node_id": zconfig.NODE["id"],
            "old_sequencer_id": zconfig.SEQUENCER["id"],
            "new_sequencer_id": new_sequencer_id,
            "timestamp": timestamp,
            "signature": utils.eth_sign(f'{zconfig.SEQUENCER["id"]}{timestamp}'),
        }
    )

    for node in zconfig.NODES.values():
        if node["id"] in {zconfig.NODE["id"], zconfig.SEQUENCER["id"]}:
            continue

        for app_name in zconfig.APPS.keys():
            missed_txs: dict[str, Any] = zdb.get_missed_txs(app_name)
            if len(missed_txs) == 0:
                continue

            try:
                response: dict[str, Any] | None = send_dispute_request(
                    node, app_name, [tx["body"] for tx in missed_txs.values()]
                )
                if not response:
                    continue

                proofs.append(response)
            except Exception:
                zlogger.exception("An unexpected error occurred:")

        if zdb.is_sequencer_down:
            try:
                response: dict[str, Any] | None = send_dispute_request(
                    node, app_name = '', missed_txs = []
                )
        
                if response:
                    proofs.append(response)
            except Exception:
                zlogger.exception("An unexpected error occurred:")
        
    if utils.is_switch_approved(proofs):
        zdb.pause_node.set()
        old_sequencer_id, new_sequencer_id = utils.get_switch_parameter_from_proofs(
            proofs
        )
        switch_sequencer(old_sequencer_id, new_sequencer_id)
        send_switch_requests(proofs)


def send_dispute_request(
    node: dict[str, Any], app_name: str, missed_txs: list[str]
) -> dict[str, Any] | None:
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
    try:
        response: requests.Response = requests.post(
            url=url, data=data, headers=zconfig.HEADERS
        )
        response_json: dict[str, Any] = response.json()
        if response_json["status"] == "success":
            return response_json.get("data")
        return None
    except requests.RequestException as error:
        zlogger.exception(f"Error sending dispute request to {node['id']}: {error}")
        return None


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
            requests.post(url=url, data=data, headers=zconfig.HEADERS)
        except Exception as error:
            zlogger.exception(f"Error sending switch request to {node['id']}: {error}")


def switch_sequencer(old_sequencer_id: str, new_sequencer_id: str) -> bool:
    """Switch the sequencer if the proofs are approved."""
    with switch_lock:
        if old_sequencer_id != zconfig.SEQUENCER["id"]:
            zlogger.warning(
                f"Old sequencer ID mismatch: expected {zconfig.SEQUENCER['id']}, got {old_sequencer_id}"
            )
            zdb.pause_node.clear()
            return False

        zconfig.update_sequencer(new_sequencer_id)
        if new_sequencer_id != zconfig.SEQUENCER["id"]:
            zlogger.warning("Sequencer was not updated")
            zdb.pause_node.clear()
            return False

        for app_name in zconfig.APPS.keys():
            all_nodes_last_finalized_tx: dict[str, Any] = (
                find_all_nodes_last_finalized_tx(app_name)
            )
            zdb.reinitialized_db(
                app_name, new_sequencer_id, all_nodes_last_finalized_tx
            )

        time.sleep(10)
        zdb.pause_node.clear()
        return True


def find_all_nodes_last_finalized_tx(app_name: str) -> dict[str, Any]:
    """Find the last finalized transaction from all nodes."""
    last_finalized_tx: dict[str, Any] = zdb.get_last_tx(
        app_name=app_name, state="finalized"
    )

    for node in zconfig.NODES.values():
        if node["id"] == zconfig.NODE["id"]:
            continue

        node_address: str = f'http://{node["host"]}:{node["port"]}'
        url: str = f"{node_address}/node/{app_name}/transactions/finalized/last"
        try:
            response: dict[str, Any] = requests.get(
                url=url, headers=zconfig.HEADERS
            ).json()
            tx: dict[str, Any] = response.get("data", {})
            if tx.get("index", 0) > last_finalized_tx.get("index", 0):
                last_finalized_tx = tx
        except Exception:
            zlogger.exception("An unexpected error occurred:")

    return last_finalized_tx
