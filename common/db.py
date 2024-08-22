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
    """A thread-safe singleton in-memory database class to manage batches of transactions and states for apps."""

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
            finalized_batches: dict[str, dict[str, Any]] = self.load_finalized_batches(app_name)
            last_finalized_batch: dict[str, Any] = max(
                (batch for batch in finalized_batches.values()),
                key=lambda batch: batch["index"],
                default={},
            )
            self.apps[app_name] = {
                "nodes_state": {},
                "batches": finalized_batches,
                "missed_batches": {},
                # TODO: store batch hash instead of batch
                "last_sequenced_batch": last_finalized_batch,
                "last_locked_batch": last_finalized_batch,
                "last_finalized_batch": last_finalized_batch,
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
    def load_finalized_batches(app_name: str, index: int | None = None) -> dict[str, Any]:
        """Load finalized batches for a given app from the snapshot file."""
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
                "An error occurred while loading finalized batches for %s: %s",
                app_name,
                error,
            )
            return {}

    def save_snapshot(self, app_name: str, index: int) -> None:
        """Save a snapshot of the finalized batches to a file."""
        snapshot_border: int = index - zconfig.SNAPSHOT_CHUNK
        remove_border: int = max(
            index - zconfig.SNAPSHOT_CHUNK * zconfig.REMOVE_CHUNK_BORDER, 0
        )

        snapshot_path: str = os.path.join(
            zconfig.SNAPSHOT_PATH, f"{index}_{app_name}.json.gz"
        )
        try:
            self.save_batches_to_file(
                app_name, index, snapshot_border, snapshot_path
            )
            self.prune_old_batches(app_name, remove_border)
            self.save_keys_to_file()
        except Exception as error:
            zlogger.exception(
                "An error occurred while saving snapshot for %s at index %d: %s",
                app_name,
                index,
                error,
            )

    def save_batches_to_file(
        self, app_name: str, index: int, snapshot_border: int, snapshot_path: str
    ) -> None:
        """Helper function to save batches to a snapshot file."""
        with gzip.open(snapshot_path, "wt", encoding="UTF-8") as file:
            json.dump(
                {
                    batch["hash"]: batch
                    for batch in self.apps[app_name]["batches"].values()
                    if batch["state"] == "finalized"
                    and snapshot_border < batch["index"] <= index
                },
                file,
            )

    def prune_old_batches(self, app_name: str, remove_border: int) -> None:
        """Helper function to prune old batches from memory."""
        self.apps[app_name]["batches"] = {
            batch["hash"]: batch
            for batch in self.apps[app_name]["batches"].values()
            if batch["state"] != "finalized" or batch["index"] > remove_border
        }

    def save_keys_to_file(self) -> None:
        """Helper function to save keys to a file."""
        keys_path: str = os.path.join(zconfig.SNAPSHOT_PATH, "keys.json.gz")
        with gzip.open(keys_path, "wt", encoding="UTF-8") as file:
            json.dump(self.keys, file)

    def get_batches(
        self, app_name: str, states: set[str], after: float = -1
    ) -> dict[str, Any]:
        """Get batches filtered by state and optionally by index."""
        batches: dict[str, Any] = {}
        i = 0
        for batch_hash, batch in list(self.apps[app_name]["batches"].items()):
            if batch["state"] in states and batch.get("index", 0) > after:
                batches[batch_hash] = batch
                i += 1
            if i >= zconfig.API_BATCHES_LIMIT:
                break
        return batches

    def get_batch(self, app_name: str, batch_hash: str) -> dict[str, Any]:
        """Get a batch by its hash."""
        return self.apps[app_name]["batches"].get(batch_hash, {})

    def get_not_finalized_batches(self, app_name: str) -> dict[str, dict[str, Any]]:
        """Get batches that are not finalized based on the finalization time border."""
        border: int = int(time.time()) - zconfig.FINALIZATION_TIME_BORDER
        batches: dict[str, Any] = self.apps[app_name]["batches"]
        return {
            batch_hash: batch
            for batch_hash, batch in list(batches.items())
            if batch["state"] == "sequenced" and batch["timestamp"] < border
        }

    def init_batches(self, app_name: str, bodies: list[str]) -> None:
        """Initialize batches of transactions with a given body."""
        if not bodies:
            return

        batches: dict[str, Any] = self.apps[app_name]["batches"]
        for body in bodies:
            now: int = int(time.time())
            batch_hash: str = utils.gen_hash(body)
            if batch_hash not in batches:
                batches[batch_hash] = {
                    "app_name": app_name,
                    "node_id": zconfig.NODE["id"],
                    "timestamp": now,
                    "state": "initialized",
                    "hash": batch_hash,
                    "body": body,
                }

            

    def get_last_batch(self, app_name: str, state: str) -> dict[str, Any]:
        """Get the last batch for a given state."""
        return self.apps.get(app_name, {}).get(f"last_{state}_batch", {})

    def sequencer_init_batches(self, app_name: str, batches_data: list[dict[str, Any]]) -> None:
        """Initialize and sequence batches."""
        if not batches_data:
            return

        batches: dict[str, Any] = self.apps[app_name]["batches"]
        last_sequenced_batch: dict[str, Any] = self.apps[app_name]["last_sequenced_batch"]
        chaining_hash: str = last_sequenced_batch.get("chaining_hash", "")
        index: int = last_sequenced_batch.get("index", 0)

        for batch in batches_data:
            if batch["hash"] in batches:
                continue
            batch_hash: str = utils.gen_hash(batch["body"])
            if batch["hash"] != batch_hash:
                zlogger.warning(
                    f"Invalid batch hash: expected {batch_hash} got {batch['hash']}"
                )
                continue

            index += 1
            chaining_hash = utils.gen_hash(chaining_hash + batch_hash)
            batch.update(
                {
                    "state": "sequenced",
                    "index": index,
                    "chaining_hash": chaining_hash,
                }
            )
            batches[batch_hash] = batch
            self.apps[app_name]["last_sequenced_batch"] = batch

    def upsert_sequenced_batches(self, app_name: str, batches_data: list[str]) -> None:
        """Upsert sequenced batches."""
        batches: dict[str, Any] = self.apps[app_name]["batches"]
        if not batches_data:
            return

        chaining_hash: str = self.apps[app_name]["last_sequenced_batch"].get(
            "chaining_hash", ""
        )
        now: int = int(time.time())
        for batch in batches_data:
            if chaining_hash or batch["index"] == 1:
                chaining_hash = utils.gen_hash(chaining_hash + batch["hash"])
                if batch["chaining_hash"] != chaining_hash:
                    zlogger.warning(
                        f"Invalid chaining hash: expected {chaining_hash} got {batch['chaining_hash']}"
                    )
                    return

            batch["sequenced_timestamp"] = now
            batches[batch["hash"]] = batch
        if chaining_hash:
            self.apps[app_name]["last_sequenced_batch"] = batch

    def update_locked_batches(self, app_name: str, sig_data: dict[str, Any]) -> None:
        """Update batches to 'locked' state up to a specified index."""
        if sig_data["index"] <= self.apps[app_name]["last_locked_batch"].get("index", 0):
            return
        batches: dict[str, Any] = self.apps[app_name]["batches"]
        for batch in list(batches.values()):
            if batch["state"] == "sequenced" and batch["index"] <= sig_data["index"]:
                batch["state"] = "locked"
        target_batch: dict[str, Any] = batches[sig_data["hash"]]
        target_batch["lock_signature"] = sig_data["signature"]
        target_batch["nonsigners"] = sig_data["nonsigners"]
        self.apps[app_name]["last_locked_batch"] = target_batch
        if not self.apps[app_name]["last_sequenced_batch"]:
            self.apps[app_name]["last_sequenced_batch"] = target_batch

    def update_finalized_batches(self, app_name: str, sig_data: dict[str, Any]) -> None:
        """Update batches to 'finalized' state up to a specified index and save snapshots."""
        if sig_data.get("index", 0) <= self.apps[app_name]["last_finalized_batch"].get(
            "index", 0
        ):
            return

        batches: dict[str, Any] = self.apps[app_name]["batches"]

        snapshot_indexes: list[int] = []
        for batch in list(batches.values()):
            if batch["state"] == "locked" and batch["index"] <= sig_data["index"]:
                batch["state"] = "finalized"

                if batch["index"] % zconfig.SNAPSHOT_CHUNK == 0:
                    snapshot_indexes.append(batch["index"])

        target_batch: dict[str, Any] = batches[sig_data["hash"]]
        target_batch["finalization_signature"] = sig_data["signature"]
        target_batch["nonsigners"] = sig_data["nonsigners"]
        self.apps[app_name]["last_finalized_batch"] = target_batch

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
            if k in list(zconfig.NODES.keys())
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

    def add_missed_batches(self, app_name: str, batches_data: dict[str, Any]) -> None:
        """Add missed batches."""
        self.apps[app_name]["missed_batches"].update(batches_data)

    def set_missed_batches(self, app_name: str, batches_data: dict[str, Any]) -> None:
        """set missed batches."""
        self.apps[app_name]["missed_batches"] = batches_data

    def empty_missed_batches(self, app_name: str) -> None:
        """Empty missed batches."""
        self.apps[app_name]["missed_batches"] = {}

    def get_missed_batches(self, app_name: str) -> dict[str, Any]:
        """Get missed batches."""
        return self.apps[app_name]["missed_batches"]

    def has_missed_batches(self) -> bool:
        """Check if there are missed batches across any app."""
        for app_name in list(zconfig.APPS.keys()):
            if self.apps[app_name]["missed_batches"]:
                return True
        return False

    def reinitialize_db(
        self,
        app_name: str,
        new_sequencer_id: str,
        all_nodes_last_finalized_batch: dict[str, Any],
    ):
        """Reinitialize the database after a switch in the sequencer."""
        self.apps[app_name]["last_sequenced_batch"] = all_nodes_last_finalized_batch
        self.apps[app_name]["last_locked_batch"] = all_nodes_last_finalized_batch
        self.apps[app_name]["last_finalized_batch"] = all_nodes_last_finalized_batch
        self.apps[app_name]["nodes_state"] = {}
        self.apps[app_name]["missed_batches"] = {}

        # TODO: should get the batches from other nodes if they are missing
        self.update_finalized_batches(
            app_name,
            all_nodes_last_finalized_batch,
        )

        if zconfig.NODE["id"] == new_sequencer_id:
            self.resequence_batches(app_name, all_nodes_last_finalized_batch)
        else:
            self.reinitialize_batches(app_name, all_nodes_last_finalized_batch)

    def resequence_batches(
        self, app_name: str, all_nodes_last_finalized_batch: dict[str, Any]
    ) -> None:
        """Resequence batches after a switch in the sequencer."""
        keys_to_retain: set[str] = {"app_name", "node_id", "timestamp", "hash", "body"}
        index: int = all_nodes_last_finalized_batch.get("index", 0)
        chaining_hash: str = all_nodes_last_finalized_batch.get("chaining_hash", "")

        not_finalized_batches: list[Any] = [
            batch
            for batch in list(self.apps[app_name]["batches"].values())
            if batch.get("state") != "finalized"
        ]
        not_finalized_batches.sort(key=lambda x: x.get("index", float("inf")))
        for batch in not_finalized_batches:
            filtered_batch = {
                key: value for key, value in batch.items() if key in keys_to_retain
            }
            index += 1
            chaining_hash = utils.gen_hash(chaining_hash + batch["hash"])
            filtered_batch.update(
                {
                    "index": index,
                    "state": "sequenced",
                    "chaining_hash": chaining_hash,
                }
            )
            self.apps[app_name]["batches"][filtered_batch["hash"]] = filtered_batch
            self.apps[app_name]["last_sequenced_batch"] = filtered_batch

    def reinitialize_batches(
        self, app_name: str, all_nodes_last_finalized_batch: dict[str, Any]
    ) -> None:
        """Reinitialize batches after a switch in the sequencer."""
        keys_to_retain: set[str] = {
            "app_name",
            "node_id",
            "timestamp",
            "hash",
            "body",
        }
        last_index: int = all_nodes_last_finalized_batch.get("index", 0)
        for batch_hash, batch in list(self.apps[app_name]["batches"].items()):
            if last_index < batch.get("index", float("inf")):
                filtered_batch = {
                    key: value for key, value in batch.items() if key in keys_to_retain
                }
                filtered_batch["state"] = "initialized"
                self.apps[app_name]["batches"][batch_hash] = filtered_batch


zdb: InMemoryDB = InMemoryDB()
