from typing import Any, Dict, List, Optional, Tuple

import requests

import config

from ..common import db
from ..common.logger import zellular_logger
from . import tss


def find_sync_point() -> Tuple[Optional[Dict[str, Any]], List[str]]:
    sorted_states: List[Dict[str, Any]] = db.get_nodes_state()
    for state in sorted_states:
        party: List[str] = [
            s["node_id"] for s in sorted_states if s["index"] >= state["index"]
        ]
        if len(party) >= config.THRESHOLD_NUMBER:
            return state, party
    return None, []


async def sync() -> None:
    zellular_logger.info("synchronizing...")
    if config.NODE["id"] != config.SEQUENCER["id"]:
        return

    state, party = find_sync_point()
    if not state:
        return

    del state["node_id"]
    sig: Optional[Dict[str, Any]] = await tss.request_sig(state, party)

    if not sig:
        return

    # convert bytes to hex (bytes is not JSON serializable)
    sig["message_bytes"] = sig["message_bytes"].hex()

    db.upsert_sync_point(state, sig)
    db.update_finalized_txs(state["index"])


async def request_nonces() -> None:
    await tss.request_nonces()


def get_last_finalized_tx() -> Dict[str, Any]:
    last_finalized_tx: Dict[str, Any] = db.get_last_tx("finalized") or {
        "index": 0,
        "chaining_hash": "",
    }

    for node in config.NODES.values():
        if node["id"] == config.NODE["id"]:
            continue

        url: str = f'http://{node["host"]}:{node["server_port"]}/node/finalized_transactions/last'
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        try:
            response: requests.Response = requests.get(url, headers=headers)
            resp: Dict[str, Any] = response.json()
            tx: Dict[str, Any] = resp.get("result", {})
            if tx.get("index", 0) > last_finalized_tx["index"]:
                last_finalized_tx = tx

            db.upsert_node_state(
                node["id"],
                tx.get("index", 0),
                tx.get("chaining_hash", ""),
            )
        except Exception:
            zellular_logger.exception("An error occurred:")

    return last_finalized_tx
