"""
This module handles synchronization processes for locked and finalized batches.
"""
import time
from typing import Any, Optional, Dict, Callable

from common import bls
from common.db import zdb, SignatureData
from config import zconfig


def _find_sync_point(
        app_name: str,
        get_sync_point_func: Callable[[str], Dict[str, Any]],
        state_key: str
) -> Optional[Dict[str, Any]]:
    """Common function to find a sync point based on given parameters."""
    nodes_state: list[Dict[str, Any]] = zdb.get_nodes_state(app_name)
    current_index: int = get_sync_point_func(app_name).get("index", 0)

    if not any(s[state_key] > current_index for s in nodes_state):
        return None

    filtered_states: list[Dict[str, Any]] = [
        s for s in nodes_state if s[state_key] >= current_index
    ]
    sorted_filtered_states: list[Dict[str, Any]] = sorted(
        filtered_states,
        key=lambda x: x[state_key],
        reverse=True
    )

    for state in sorted_filtered_states:
        party: set[str] = {
            s["node_id"] for s in sorted_filtered_states
            if s[state_key] >= state[state_key]
        }
        stake = sum(zconfig.NODES[node_id]['stake'] for node_id in party)
        stake += zconfig.NODE["stake"]
        if 100 * stake / zconfig.TOTAL_STAKE >= zconfig.THRESHOLD_PERCENT:
            return {"state": state, "party": party}

    return None


def find_locked_sync_point(app_name: str) -> Dict[str, Any] | None:
    """Find the locked sync point for a given app."""
    return _find_sync_point(
        app_name,
        zdb.get_locked_sync_point,
        "sequenced_index"
    )


def find_finalized_sync_point(app_name: str) -> Dict[str, Any] | None:
    """Find the finalized sync point for a given app."""
    return _find_sync_point(
        app_name,
        zdb.get_finalized_sync_point,
        "locked_index"
    )


def sync() -> None:
    """Synchronize all apps."""
    if zconfig.NODE["id"] != zconfig.SEQUENCER["id"]:
        return

    for app_name in list(zconfig.APPS.keys()):
        sync_app(app_name)


def sync_app(app_name: str) -> None:
    """Synchronize a specific app synchronously."""

    # Process locked sync point
    locked_sync_point: Optional[Dict[str, Any]] = find_locked_sync_point(app_name)
    if locked_sync_point:
        locked_data: Dict[str, Any] = {
            "app_name": app_name,
            "state": "sequenced",
            "index": locked_sync_point["state"]["sequenced_index"],
            "hash": locked_sync_point["state"]["sequenced_hash"],
            "chaining_hash": locked_sync_point["state"]["sequenced_chaining_hash"],
        }
        lock_signature: Optional[Dict[str, Any]] = bls.gather_and_aggregate_signatures(
            data=locked_data, node_ids=locked_sync_point["party"]
        )

        if lock_signature:
            locked_data.update(lock_signature)
            locked_data = {
                key: value
                for key, value in locked_data.items()
                if key in SignatureData.__annotations__
            }
            zdb.upsert_locked_sync_point(app_name=app_name, signature_data=locked_data)
            zdb.lock_batches(
                app_name=app_name,
                signature_data=locked_data,
            )

    ############################################################
    ############################################################
    ############################################################
    ############################################################

    # Process finalized sync point
    finalized_sync_point: Optional[Dict[str, Any]] = find_finalized_sync_point(app_name)
    if finalized_sync_point:
        finalized_data: Dict[str, Any] = {
            "app_name": app_name,
            "state": "locked",
            "index": finalized_sync_point["state"]["locked_index"],
            "hash": finalized_sync_point["state"]["locked_hash"],
            "chaining_hash": finalized_sync_point["state"]["locked_chaining_hash"],
        }
        finalization_signature: Optional[Dict[str, Any]] = bls.gather_and_aggregate_signatures(
            data=finalized_data, node_ids=finalized_sync_point["party"]
        )
        if finalization_signature:
            finalized_data.update(finalization_signature)
            finalized_data = {
                key: value
                for key, value in finalized_data.items()
                if key in SignatureData.__annotations__
            }
            zdb.upsert_finalized_sync_point(app_name=app_name, signature_data=finalized_data)
            zdb.finalize_batches(
                app_name=app_name,
                signature_data=finalized_data,
            )
