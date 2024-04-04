from typing import Any, Dict, List, Optional, Tuple

from config import zconfig

from ..common.db import zdb
from ..common.logger import zlogger
from . import tss


def find_sync_point() -> Tuple[Optional[Dict[str, Any]], List[str]]:
    sorted_states: List[Dict[str, Any]] = zdb.nodes_state.get_nodes_state()
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

    zdb.nodes_state.upsert_sync_point(state, sig)
    zdb.txs.update_finalized_txs(state["index"])


async def request_nonces() -> None:
    await tss.request_nonces()
