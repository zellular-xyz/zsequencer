"""
This module handles synchronization processes for locked and finalized transactions.
"""

from typing import Any

from common import bls
from common.db import zdb
from config import zconfig


def find_locked_sync_point(app_name: str) -> dict[str, Any] | None:
    """Find the locked sync point for a given app."""
    nodes_state: list[dict[str, Any]] = zdb.get_nodes_state(app_name)
    locked_index: int = zdb.get_locked_sync_point(app_name).get("index", 0)
    filtered_states: list[dict[str, Any]] = [
        s for s in nodes_state if s["sequenced_index"] >= locked_index
    ]
    sorted_filtered_states: list[dict[str, Any]] = sorted(
        filtered_states,
        key=lambda x: x["sequenced_index"],
        reverse=True,
    )
    for state in sorted_filtered_states:
        party: set[str] = {
            s["node_id"]
            for s in sorted_filtered_states
            if s["sequenced_index"] >= state["sequenced_index"]
        }
        stake = sum([zconfig.NODES[node_id]['stake'] for node_id in party])
        stake += zconfig.NODE["stake"]
        if 100 * stake / zconfig.TOTAL_STAKE >= zconfig.THRESHOLD_PERCENT:
            return {"state": state, "party": party}
    return None


def find_finalized_sync_point(app_name: str) -> dict[str, Any] | None:
    """Find the finalized sync point for a given app."""
    nodes_state: list[dict[str, Any]] = zdb.get_nodes_state(app_name)
    finalized_index: int = zdb.get_finalized_sync_point(app_name).get("index", 0)
    filtered_states: list[dict[str, Any]] = [
        s for s in nodes_state if s["locked_index"] >= finalized_index
    ]

    sorted_filtered_states: list[dict[str, Any]] = sorted(
        filtered_states,
        key=lambda x: x["locked_index"],
        reverse=True,
    )
    for state in sorted_filtered_states:
        party: set[str] = {
            s["node_id"]
            for s in sorted_filtered_states
            if s["locked_index"] >= state["locked_index"]
        }
        stake = sum([zconfig.NODES[node_id]['stake'] for node_id in party])
        stake += zconfig.NODE["stake"]
        if 100 * stake / zconfig.TOTAL_STAKE >= zconfig.THRESHOLD_PERCENT:
            return {"state": state, "party": party}
    return None


async def sync() -> None:
    """Synchronize all apps."""
    if zconfig.NODE["id"] != zconfig.SEQUENCER["id"]:
        return

    for app_name in zconfig.APPS.keys():
        await sync_app(app_name)


async def sync_app(app_name: str) -> None:
    """Synchronize a specific app."""
    locked_sync_point: dict[str, Any] | None = find_locked_sync_point(app_name)
    if locked_sync_point:
        locked_data: dict[str, Any] = {
            "app_name": app_name,
            "state": "sequenced",
            "index": locked_sync_point["state"]["sequenced_index"],
            "hash": locked_sync_point["state"]["sequenced_hash"],
            "chaining_hash": locked_sync_point["state"]["sequenced_chaining_hash"],
        }
        lock_signature: (
            dict[str, Any] | None
        ) = await bls.gather_and_aggregate_signatures(
            data=locked_data, node_ids=locked_sync_point["party"]
        )

        if lock_signature:
            locked_data.update(lock_signature)
            zdb.upsert_locked_sync_point(app_name=app_name, state=locked_data)
            zdb.update_locked_txs(
                app_name=app_name,
                sig_data=locked_data,
            )

    finalized_sync_point: dict[str, Any] | None = find_finalized_sync_point(app_name)
    if finalized_sync_point:
        finalized_data: dict[str, Any] = {
            "app_name": app_name,
            "state": "locked",
            "index": finalized_sync_point["state"]["locked_index"],
            "hash": finalized_sync_point["state"]["locked_hash"],
            "chaining_hash": finalized_sync_point["state"]["locked_chaining_hash"],
        }
        finalization_signature: (
            dict[str, Any] | None
        ) = await bls.gather_and_aggregate_signatures(
            data=finalized_data, node_ids=finalized_sync_point["party"]
        )
        if finalization_signature:
            finalized_data.update(finalization_signature)
            zdb.upsert_finalized_sync_point(app_name=app_name, state=finalized_data)
            zdb.update_finalized_txs(
                app_name=app_name,
                sig_data=finalized_data,
            )
