from typing import Any, Dict, List, Optional, Tuple

from config import zconfig

from ..common import utils
from ..common.db import zdb
from ..common.logger import zlogger
from . import tss


def sequence_transactions(txs: List[Dict[str, Any]]):
    last_synced_tx: Dict[str, Any] = zdb.last_sequenced_tx
    last_chaining_hash: str = last_synced_tx.get("chaining_hash", "")
    index: int = last_synced_tx.get("index", 0)
    for tx in txs:
        tx_hash: str = utils.gen_tx_hash(tx)
        if tx_hash in zdb.transactions:
            continue
        index += 1
        tx["index"] = index
        tx["hash"] = tx_hash
        tx["state"] = "sequenced"
        tx["chaining_hash"] = utils.gen_chaining_hash(last_chaining_hash, tx_hash)
        last_chaining_hash = tx["chaining_hash"]
    zdb.last_sequenced_tx = tx
    zdb.insert_txs(txs)


def find_sync_point() -> Tuple[Optional[Dict[str, Any]], List[str]]:
    sorted_states: List[Dict[str, Any]] = zdb.get_nodes_state()
    for state in sorted_states:
        party: List[str] = [
            s["node_id"] for s in sorted_states if s["index"] >= state["index"]
        ]
        if len(party) >= zconfig.THRESHOLD_NUMBER:
            return state, party
    return None, []


async def sync() -> None:
    zlogger.info("synchronizing...")
    if zconfig.NODE["id"] != zconfig.SEQUENCER["id"]:
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

    zdb.upsert_sync_point(state, sig)
    zdb.update_finalized_txs(state["index"])


async def request_nonces() -> None:
    await tss.request_nonces()
