import gzip
import json
import os
import threading
import time
from typing import Any

from config import zconfig

from . import utils
from .logger import zlogger


class InMemoryDB:
    """A thread-safe singleton in-memory database class to manage apps transactions and states."""

    _instance: "InMemoryDB | None" = None
    lock: threading.Lock = threading.Lock()

    def __new__(cls) -> "InMemoryDB":
        """Singleton pattern implementation to ensure only one instance exists."""
        with cls.lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialize()
            return cls._instance

    def _initialize(self) -> None:
        """Initialize the InMemoryDB instance."""
        self.lock = threading.Lock()
        self.pause_node = threading.Event()

        self.apps: dict[str, Any] = {}
        self.keys: dict[str, Any] = {}
        self.is_sequencer_down: bool = False
        self.load_state()

    def load_state(self) -> None:
        """Load the initial state from the snapshot files."""
        self.keys = self.load_keys()

        for app_name in getattr(zconfig, "APPS", []):
            finalized_txs: dict[str, dict[str, Any]] = self.load_finalized_txs(app_name)
            last_finalized_tx: dict[str, Any] = max(
                (tx for tx in finalized_txs.values()),
                key=lambda tx: tx["index"],
                default={},
            )
            self.apps[app_name] = {
                "nodes_state": {},
                "transactions": finalized_txs,
                "missed_txs": {},
                # TODO: store tx hash instead of tx
                "last_sequenced_tx": last_finalized_tx,
                "last_locked_tx": last_finalized_tx,
                "last_finalized_tx": last_finalized_tx,
            }

    @staticmethod
    def load_keys() -> dict[str, Any]:
        """Load keys from the snapshot file."""
        keys_path: str = os.path.join(zconfig.SNAPSHOT_PATH, "keys.json.gz")
        try:
            with gzip.open(keys_path, "rt", encoding="UTF-8") as file:
                return json.load(file)
        except (OSError, IOError, json.JSONDecodeError):
            return {}

    @staticmethod
    def load_finalized_txs(app_name: str, index: int | None = None) -> dict[str, Any]:
        """Load finalized transactions for a given app from the snapshot file."""
        if index == 0:
            return {}

        if index is None:
            snapshots: list[str] = [
                file
                for file in os.listdir(zconfig.SNAPSHOT_PATH)
                if file.endswith(".json.gz")
            ]
            if not snapshots:
                return {}

            index = max(
                (int(x.split("_")[0]) for x in snapshots if x.split("_")[0].isdigit()),
                default=0,
            )

        snapshot_path: str = os.path.join(
            zconfig.SNAPSHOT_PATH, f"{index}_{app_name}.json.gz"
        )
        try:
            with gzip.open(snapshot_path, "rt", encoding="UTF-8") as file:
                return json.load(file)
        except (OSError, IOError, json.JSONDecodeError) as error:
            zlogger.exception(
                "An error occurred while loading finalized transactions for %s: %s",
                app_name,
                error,
            )
            return {}

    def save_snapshot(self, app_name: str, index: int) -> None:
        """Save a snapshot of the finalized transactions to a file."""
        snapshot_border: int = index - zconfig.SNAPSHOT_CHUNK
        remove_border: int = max(
            index - zconfig.SNAPSHOT_CHUNK * zconfig.REMOVE_CHUNK_BORDER, 0
        )

        snapshot_path: str = os.path.join(
            zconfig.SNAPSHOT_PATH, f"{index}_{app_name}.json.gz"
        )
        try:
            self.save_transactions_to_file(
                app_name, index, snapshot_border, snapshot_path
            )
            self.prune_old_transactions(app_name, remove_border)
            self.save_keys_to_file()
        except Exception as error:
            zlogger.exception(
                "An error occurred while saving snapshot for %s at index %d: %s",
                app_name,
                index,
                error,
            )

    def save_transactions_to_file(
        self, app_name: str, index: int, snapshot_border: int, snapshot_path: str
    ) -> None:
        """Helper function to save transactions to a snapshot file."""
        with gzip.open(snapshot_path, "wt", encoding="UTF-8") as file:
            json.dump(
                {
                    tx["hash"]: tx
                    for tx in self.apps[app_name]["transactions"].values()
                    if tx["state"] == "finalized"
                    and snapshot_border < tx["index"] <= index
                },
                file,
            )

    def prune_old_transactions(self, app_name: str, remove_border: int) -> None:
        """Helper function to prune old transactions from memory."""
        self.apps[app_name]["transactions"] = {
            tx["hash"]: tx
            for tx in self.apps[app_name]["transactions"].values()
            if tx["state"] != "finalized" or tx["index"] > remove_border
        }

    def save_keys_to_file(self) -> None:
        """Helper function to save keys to a file."""
        keys_path: str = os.path.join(zconfig.SNAPSHOT_PATH, "keys.json.gz")
        with gzip.open(keys_path, "wt", encoding="UTF-8") as file:
            json.dump(self.keys, file)

    def get_txs(
        self, app_name: str, states: set[str], after: float = float("-inf")
    ) -> dict[str, Any]:
        """Get transactions filtered by state and optionally by index."""
        transactions: dict[str, Any] = self.apps[app_name]["transactions"].copy()
        return {
            tx_hash: tx
            for tx_hash, tx in transactions.items()
            if tx["state"] in states and tx.get("index", 0) > after
        }

    def get_tx(self, app_name: str, tx_hash: str) -> dict[str, Any]:
        """Get a transaction by its hash."""
        return self.apps[app_name]["transactions"].get(tx_hash, {})

    def get_not_finalized_txs(self, app_name: str) -> dict[str, dict[str, Any]]:
        """Get transactions that are not finalized based on the finalization time border."""
        border: int = int(time.time()) - zconfig.FINALIZATION_TIME_BORDER
        transactions: dict[str, Any] = self.apps[app_name]["transactions"]
        return {
            tx_hash: tx
            for tx_hash, tx in list(transactions.items())
            if tx["state"] == "sequenced" and tx["timestamp"] < border
        }

    def init_txs(self, app_name: str, bodies: list[str]) -> None:
        """Initialize transactions with given bodies."""
        if not bodies:
            return

        transactions: dict[str, Any] = self.apps[app_name]["transactions"]
        now: int = int(time.time())
        for body in bodies:
            tx_hash: str = utils.gen_hash(body)
            if tx_hash not in transactions:
                transactions[tx_hash] = {
                    "app_name": app_name,
                    "node_id": zconfig.NODE["id"],
                    "timestamp": now,
                    "state": "initialized",
                    "hash": tx_hash,
                    "body": body,
                }

    def get_last_tx(self, app_name: str, state: str) -> dict[str, Any]:
        """Get the last transaction for a given state."""
        return self.apps.get(app_name, {}).get(f"last_{state}_tx", {})

    def sequencer_init_txs(self, app_name: str, txs: list[dict[str, Any]]) -> None:
        """Initialize and sequence transactions."""
        if not txs:
            return

        transactions: dict[str, Any] = self.apps[app_name]["transactions"]
        last_sequenced_tx: dict[str, Any] = self.apps[app_name]["last_sequenced_tx"]
        chaining_hash: str = last_sequenced_tx.get("chaining_hash", "")
        index: int = last_sequenced_tx.get("index", 0)

        for tx in txs:
            if tx["hash"] in transactions:
                continue

            tx_hash: str = utils.gen_hash(tx["body"])
            if tx["hash"] != tx_hash:
                zlogger.warning(
                    f"Invalid transaction hash: expected {tx_hash} got {tx['hash']}"
                )
                continue

            index += 1
            chaining_hash = utils.gen_hash(chaining_hash + tx_hash)
            tx.update(
                {
                    "state": "sequenced",
                    "index": index,
                    "chaining_hash": chaining_hash,
                }
            )
            transactions[tx_hash] = tx
            self.apps[app_name]["last_sequenced_tx"] = tx

    def upsert_sequenced_txs(self, app_name: str, txs: list[dict[str, Any]]) -> None:
        """Upsert sequenced transactions."""
        transactions: dict[str, Any] = self.apps[app_name]["transactions"]
        if not txs:
            return

        chaining_hash: str = self.apps[app_name]["last_sequenced_tx"].get(
            "chaining_hash", ""
        )
        now: int = int(time.time())
        for tx in txs:
            # TODO: all nodes should check the hashes
            if tx["node_id"] == zconfig.NODE["id"]:
                if tx["body"] != transactions[tx["hash"]]["body"]:
                    zlogger.warning("Invalid transaction hash")
                    continue

                chaining_hash = utils.gen_hash(chaining_hash + tx["hash"])
                if tx["chaining_hash"] != chaining_hash:
                    zlogger.warning(
                        f"Invalid chaining hash: expected {chaining_hash} got {tx['chaining_hash']}"
                    )
                    continue

            tx["sequenced_timestamp"] = now
            transactions[tx["hash"]] = tx
        self.apps[app_name]["last_sequenced_tx"] = tx

    def update_locked_txs(self, app_name: str, sig_data: dict[str, Any]) -> None:
        """Update transactions to 'locked' state up to a specified index."""
        if sig_data["index"] <= self.apps[app_name]["last_locked_tx"].get("index", 0):
            return
        transactions: dict[str, Any] = self.apps[app_name]["transactions"]
        for tx in list(transactions.values()):
            if tx["state"] == "sequenced" and tx["index"] <= sig_data["index"]:
                tx["state"] = "locked"
        target_tx: dict[str, Any] = transactions[sig_data["hash"]]
        target_tx["lock_signature"] = sig_data["signature"]
        target_tx["nonsigners"] = sig_data["nonsigners"]
        self.apps[app_name]["last_locked_tx"] = target_tx

    def update_finalized_txs(self, app_name: str, sig_data: dict[str, Any]) -> None:
        """Update transactions to 'finalized' state up to a specified index and save snapshots."""
        if sig_data.get("index", 0) <= self.apps[app_name]["last_finalized_tx"].get(
            "index", 0
        ):
            return

        transactions: dict[str, Any] = self.apps[app_name]["transactions"]

        snapshot_indexes: list[int] = []
        for tx in list(transactions.values()):
            if tx["index"] <= sig_data["index"]:
                tx["state"] = "finalized"

                if tx["index"] % zconfig.SNAPSHOT_CHUNK == 0:
                    snapshot_indexes.append(tx["index"])

        target_tx: dict[str, Any] = transactions[sig_data["hash"]]
        target_tx["finalization_signature"] = sig_data["signature"]
        target_tx["nonsigners"] = sig_data["nonsigners"]
        self.apps[app_name]["last_finalized_tx"] = target_tx

        for snapshot_index in snapshot_indexes:
            self.save_snapshot(app_name, snapshot_index)

    def upsert_node_state(
        self,
        node_state: dict[str, Any],
    ) -> None:
        """Upsert the state of a node."""
        if not node_state["sequenced_index"]:
            return

        app_name: str = node_state["app_name"]
        node_id: str = node_state["node_id"]
        self.apps[app_name]["nodes_state"][node_id] = node_state

    def get_nodes_state(self, app_name: str) -> list[dict[str, Any]]:
        """Get the state of all nodes for a given app."""
        return [
            v
            for k, v in self.apps[app_name]["nodes_state"].items()
            if k in zconfig.NODES
        ]

    def upsert_locked_sync_point(self, app_name: str, state: dict[str, Any]) -> None:
        """Upsert the locked sync point for an app."""
        self.apps[app_name]["nodes_state"]["locked_sync_point"] = {
            "index": state["index"],
            "chaining_hash": state["chaining_hash"],
            "hash": state["hash"],
            "signature": state["signature"],
            "nonsigners": state["nonsigners"],
        }

    def upsert_finalized_sync_point(self, app_name: str, state: dict[str, Any]) -> None:
        """Upsert the finalized sync point for an app."""
        self.apps[app_name]["nodes_state"]["finalized_sync_point"] = {
            "index": state["index"],
            "chaining_hash": state["chaining_hash"],
            "hash": state["hash"],
            "signature": state["signature"],
            "nonsigners": state["nonsigners"],
        }

    def get_locked_sync_point(self, app_name: str) -> dict[str, Any]:
        """Get the locked sync point for an app."""
        return self.apps[app_name]["nodes_state"].get("locked_sync_point", {})

    def get_finalized_sync_point(self, app_name: str) -> dict[str, Any]:
        """Get the finalized sync point for an app."""
        return self.apps[app_name]["nodes_state"].get("finalized_sync_point", {})

    def add_missed_txs(self, app_name: str, txs: dict[str, dict[str, Any]]) -> None:
        """Add missed transactions."""
        self.apps[app_name]["missed_txs"].update(txs)

    def set_missed_txs(self, app_name: str, txs: dict[str, dict[str, Any]]) -> None:
        """set missed transactions."""
        self.apps[app_name]["missed_txs"] = txs

    def empty_missed_txs(self, app_name: str) -> None:
        """Empty missed transactions."""
        self.apps[app_name]["missed_txs"] = {}

    def get_missed_txs(self, app_name: str) -> dict[str, Any]:
        """Get missed transactions."""
        return self.apps[app_name]["missed_txs"]

    def has_missed_txs(self) -> bool:
        """Check if there are missed transactions across any app."""
        for app_name in zconfig.APPS:
            if self.apps[app_name]["missed_txs"]:
                return True
        return False

    def reinitialized_db(
        self,
        app_name: str,
        new_sequencer_id: str,
        all_nodes_last_finalized_tx: dict[str, Any],
    ):
        """Reinitialized the database after a switch in the sequencer."""
        self.apps[app_name]["last_sequenced_tx"] = all_nodes_last_finalized_tx
        self.apps[app_name]["last_locked_tx"] = all_nodes_last_finalized_tx
        self.apps[app_name]["last_finalized_tx"] = all_nodes_last_finalized_tx
        self.apps[app_name]["nodes_state"] = {}
        self.apps[app_name]["missed_txs"] = {}

        # TODO: should get the transactions from other nodes if they are missing
        self.update_finalized_txs(
            app_name,
            all_nodes_last_finalized_tx,
        )

        if zconfig.NODE["id"] == new_sequencer_id:
            self.resequence_txs(app_name, all_nodes_last_finalized_tx)
        else:
            self.reinitialized_txs(app_name, all_nodes_last_finalized_tx)

    def resequence_txs(
        self, app_name: str, all_nodes_last_finalized_tx: dict[str, Any]
    ) -> None:
        """Resequence transactions after a switch in the sequencer."""
        keys_to_retain: set[str] = {"app_name", "node_id", "timestamp", "hash", "body"}
        index: int = all_nodes_last_finalized_tx.get("index", 0)
        chaining_hash: str = all_nodes_last_finalized_tx.get("chaining_hash", "")

        not_finalized_txs: list[Any] = [
            tx
            for tx in list(self.apps[app_name]["transactions"].values())
            if tx.get("state") != "finalized"
        ]
        not_finalized_txs.sort(key=lambda x: x.get("index", float("inf")))
        for tx in not_finalized_txs:
            filtered_tx = {
                key: value for key, value in tx.items() if key in keys_to_retain
            }
            index += 1
            chaining_hash = utils.gen_hash(chaining_hash + tx["hash"])
            filtered_tx.update(
                {
                    "index": index,
                    "state": "sequenced",
                    "chaining_hash": chaining_hash,
                }
            )
            self.apps[app_name]["transactions"][filtered_tx["hash"]] = filtered_tx
            self.apps[app_name]["last_sequenced_tx"] = filtered_tx

    def reinitialized_txs(
        self, app_name: str, all_nodes_last_finalized_tx: dict[str, Any]
    ) -> None:
        """Reinitialized transactions after a switch in the sequencer."""
        keys_to_retain: set[str] = {
            "app_name",
            "node_id",
            "timestamp",
            "hash",
            "body",
        }
        last_index: int = all_nodes_last_finalized_tx.get("index", 0)
        for tx_hash, tx in list(self.apps[app_name]["transactions"].items()):
            if last_index < tx.get("index", float("inf")):
                filtered_tx = {
                    key: value for key, value in tx.items() if key in keys_to_retain
                }
                filtered_tx["state"] = "initialized"
                self.apps[app_name]["transactions"][tx_hash] = filtered_tx


zdb: InMemoryDB = InMemoryDB()
