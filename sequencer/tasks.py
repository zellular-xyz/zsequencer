import json
from typing import Any, Dict, List, Optional, Tuple

from config import zconfig

from ..common.db import zdb
from ..common.logger import zlogger
from . import tss


def find_sync_point() -> Tuple[Dict[str, Any], List[str]]:
    sorted_states: List[Dict[str, Any]] = zdb.get_nodes_state()
    for state in sorted_states:
        party: List[str] = [
            s["node_id"] for s in sorted_states if s["index"] >= state["index"]
        ]
        if len(party) >= zconfig.THRESHOLD_NUMBER:
            return state, party
    return {}, []


async def sync() -> None:
    zlogger.info("synchronizing...")
    if zconfig.NODE["id"] != zconfig.SEQUENCER["id"]:
        return

    state, party = find_sync_point()
    if not state.get("index"):
        return

    del state["node_id"]
    sig: Optional[Dict[str, Any]] = await tss.request_sig(state, party)

    if not sig:
        return

    # convert bytes to hex (bytes is not JSON serializable)
    sig["message_bytes"] = sig["message_bytes"].hex()

    zdb.upsert_sync_point(state, sig)
    zdb.update_finalized_txs(state["index"])
    zdb.insert_sync_sig(
        {
            "index": state["index"],
            "chaining_hash": state["chaining_hash"],
            "hash": state["hash"],
            "sig": json.dumps(sig),
        }
    )


async def request_nonces() -> None:
    await tss.request_nonces()
