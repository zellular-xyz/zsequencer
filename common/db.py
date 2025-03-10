from __future__ import annotations
import gzip
import json
import math
import os
import threading
import time
from typing import Any
from threading import Thread
from config import zconfig
from utils import get_file_content
from . import utils
from .logger import zlogger
from typing import Literal
import itertools
import portion  # type: ignore[import-untyped]
from typing import TypedDict
from collections.abc import Iterable, Callable

State = Literal["initialized", "sequenced", "locked", "finalized"]
OperationalState = Literal["sequenced", "locked", "finalized"]


class App(TypedDict, total=False):
    # TODO: Annotate the keys and values.
    nodes_state: dict[str, Any]
    initialized_batches_map: dict[str, Batch]
    operational_batches_sequence: list[Batch]
    # TODO: Check if it's necessary.
    operational_batches_hash_index_map: dict[str, int]
    missed_batches_map: dict[str, Batch]
    # TODO: Store the batch hash or index instead of the entire batch.
    last_sequenced_batch: Batch
    last_locked_batch: Batch
    last_finalized_batch: Batch


class Batch(TypedDict, total=False):
    app_name: str
    node_id: str
    timestamp: int
    body: str
    index: int
    hash: str
    state: State
    chaining_hash: str
    lock_signature: str
    locked_nonsigners: list[str]
    locked_tag: int
    finalization_signature: str
    finalized_nonsigners: list[str]
    finalized_tag: int


class SignatureData(TypedDict, total=False):
    index: int
    chaining_hash: str
    hash: str
    signature: str
    nonsigners: list[str]
    tag: int


class InMemoryDB:
    """In-memory database class to manage batches of transactions and states for apps."""

    _GLOBAL_FIRST_BATCH_INDEX = 1
    _BEFORE_GLOBAL_FIRST_BATCH_INDEX = _GLOBAL_FIRST_BATCH_INDEX - 1
    _NOT_SET_BATCH_INDEX = _GLOBAL_FIRST_BATCH_INDEX - 1

    # TODO: It seems that there are some possible race-condition situations where
    # multiple data structures are mutated together, or a chain of methods needs
    # to be called atomically.

    def __init__(self) -> None:
        """Initialize the InMemoryDB instance."""
        self.sequencer_put_batches_lock = threading.Lock()
        self.pause_node = threading.Event()
        self._last_saved_index = self._BEFORE_GLOBAL_FIRST_BATCH_INDEX
        self.is_sequencer_down = False
        self.apps = self._load_finalized_batches_for_all_apps()
        self._fetching_thread = Thread(
            target=self._fetch_apps_and_network_state_periodically
        )
        self._fetching_thread.start()

    def _fetch_apps(self) -> None:
        """Fetchs the apps data."""
        data = get_file_content(zconfig.APPS_FILE)

        new_apps: dict[str, App] = {}
        for app_name in data:
            if app_name in self.apps:
                new_apps[app_name] = self.apps[app_name]
            else:
                new_apps[app_name] = {
                    "nodes_state": {},
                    "initialized_batches_map": {},
                    "operational_batches_sequence": [],
                    "operational_batches_hash_index_map": {},
                    "missed_batches_map": {},
                    "last_sequenced_batch": {},
                    "last_locked_batch": {},
                    "last_finalized_batch": {},
                }

        zconfig.APPS.update(data)
        self.apps.update(new_apps)
        for app_name in zconfig.APPS:
            snapshot_path = os.path.join(
                zconfig.SNAPSHOT_PATH, zconfig.VERSION, app_name
            )
            os.makedirs(snapshot_path, exist_ok=True)

    def _fetch_apps_and_network_state_periodically(self) -> None:
        """Periodically fetches apps and nodes data."""
        while True:
            try:
                self._fetch_apps()
            except:
                zlogger.error("An unexpected error occurred while fetching apps data.")

            try:
                zconfig.fetch_network_state()
            except:
                zlogger.error(
                    "An unexpected error occurred while fetching network state."
                )

            time.sleep(zconfig.FETCH_APPS_AND_NODES_INTERVAL)

    @classmethod
    def _load_finalized_batches_for_all_apps(cls) -> dict[str, App]:
        """Load and return the initial state from the snapshot files."""
        result: dict[str, App] = {}

        # TODO: Replace with dot operator.
        for app_name in getattr(zconfig, "APPS", []):
            finalized_batches = cls._load_finalized_batches(app_name)
            last_finalized_batch = finalized_batches[-1] if finalized_batches else {}
            result[app_name] = {
                "nodes_state": {},
                "initialized_batches_map": {},
                "operational_batches_sequence": finalized_batches,
                "operational_batches_hash_index_map": cls._generate_batches_hash_index_map(
                    finalized_batches
                ),
                "missed_batches_map": {},
                "last_sequenced_batch": last_finalized_batch,
                "last_locked_batch": last_finalized_batch,
                "last_finalized_batch": last_finalized_batch,
            }

        return result

    # TODO: Remove the unused method.
    @staticmethod
    def _load_keys() -> dict[str, Any]:
        """Load keys from the snapshot file."""
        keys_path = os.path.join(zconfig.SNAPSHOT_PATH, "keys.json.gz")
        try:
            with gzip.open(keys_path, "rt", encoding="UTF-8") as file:
                return json.load(file)
        except (OSError, IOError, json.JSONDecodeError):
            return {}

    @classmethod
    def _load_finalized_batches(
        cls, app_name: str, index: int | None = None
    ) -> list[Batch]:
        """Load finalized batches for a given app from the snapshot file."""
        snapshot_dir = os.path.join(zconfig.SNAPSHOT_PATH, zconfig.VERSION, app_name)
        if index is None:
            effective_index = 0
            snapshots = sorted(
                file for file in os.listdir(snapshot_dir) if file.endswith(".json.gz")
            )
            if snapshots:
                effective_index = int(snapshots[-1].split(".")[0])
        else:
            effective_index = (
                math.ceil(index / zconfig.SNAPSHOT_CHUNK) * zconfig.SNAPSHOT_CHUNK
            )

        if effective_index <= 0:
            return []

        try:
            with gzip.open(
                snapshot_dir + f"/{str(effective_index).zfill(7)}.json.gz",
                "rt",
                encoding="UTF-8",
            ) as file:
                return json.load(file)
        except (FileNotFoundError, EOFError):
            pass
        except (OSError, IOError, json.JSONDecodeError) as error:
            zlogger.exception(
                "An error occurred while loading finalized batches for %s: %s",
                app_name,
                error,
            )
        return []

    def _save_finalized_chunk_then_prune(
        self, app_name: str, snapshot_index: int
    ) -> None:
        try:
            snapshot_border_index = max(
                snapshot_index - zconfig.SNAPSHOT_CHUNK,
                self._BEFORE_GLOBAL_FIRST_BATCH_INDEX,
            )
            self._save_finalized_batches_chunk_to_file(
                app_name,
                border_index=snapshot_border_index,
                end_index=snapshot_index,
            )

            remove_border_index = max(
                snapshot_index - zconfig.SNAPSHOT_CHUNK * zconfig.REMOVE_CHUNK_BORDER,
                self._BEFORE_GLOBAL_FIRST_BATCH_INDEX,
            )
            self._prune_old_finalized_batches(app_name, remove_border_index)
        except Exception as error:
            zlogger.exception(
                "An error occurred while saving snapshot for %s at index %d: %s",
                app_name,
                snapshot_index,
                error,
            )

    def _save_finalized_batches_chunk_to_file(
        self, app_name: str, border_index: int, end_index: int
    ) -> None:
        snapshot_dir = os.path.join(zconfig.SNAPSHOT_PATH, zconfig.VERSION, app_name)
        with gzip.open(
            snapshot_dir + f"/{str(end_index).zfill(7)}.json.gz", "wt", encoding="UTF-8"
        ) as file:
            json.dump(
                self._filter_operational_batches_sequence(
                    app_name,
                    portion.openclosed(border_index, end_index),
                ),
                file,
            )

    def _prune_old_finalized_batches(self, app_name: str, border_index: int) -> None:
        self.apps[app_name]["operational_batches_sequence"] = (
            self._filter_operational_batches_sequence(
                app_name,
                portion.open(border_index, portion.inf),
            )
        )
        self.apps[app_name]["operational_batches_hash_index_map"] = (
            self._generate_batches_hash_index_map(
                self.apps[app_name]["operational_batches_sequence"]
            )
        )

    def get_initialized_batches_map(self, app_name: str) -> dict[str, Batch]:
        # NOTE: We copy the dictionary in order to make it safe to work on it
        # without the fear of change in the middle of processing.
        return self.apps[app_name]["initialized_batches_map"].copy()

    def get_global_operational_batches_sequence(
        self,
        app_name: str,
        state: OperationalState | None = None,
        after: int = _BEFORE_GLOBAL_FIRST_BATCH_INDEX,
    ) -> list[Batch]:
        """Get batches filtered by state and optionally by index."""
        batches_sequence: list[Batch] = []
        batches_hash_set: set[str] = set()  # TODO: Check if this is necessary.

        includes_finalized_batches = state is None or state == "finalized"

        if includes_finalized_batches:
            last_finalized_index = self.apps[app_name]["last_finalized_batch"].get(
                "index", self._BEFORE_GLOBAL_FIRST_BATCH_INDEX
            )
            current_chunk = math.ceil((after + 1) / zconfig.SNAPSHOT_CHUNK)
            next_chunk = math.ceil(
                (after + 1 + zconfig.API_BATCHES_LIMIT) / zconfig.SNAPSHOT_CHUNK
            )
            finalized_chunk = math.ceil(last_finalized_index / zconfig.SNAPSHOT_CHUNK)

            if current_chunk != finalized_chunk:
                loaded_finalized_batches = self._load_finalized_batches(
                    app_name, after + 1
                )
                self._append_unique_batches_after_index(
                    loaded_finalized_batches,
                    after,
                    batches_sequence,
                    batches_hash_set,
                )

            if len(batches_sequence) < zconfig.API_BATCHES_LIMIT and next_chunk not in [
                current_chunk,
                finalized_chunk,
            ]:
                loaded_finalized_batches = self._load_finalized_batches(
                    app_name, after + 1 + len(batches_sequence)
                )
                self._append_unique_batches_after_index(
                    loaded_finalized_batches,
                    after,
                    batches_sequence,
                    batches_hash_set,
                )

        self._append_unique_batches_after_index(
            self._filter_operational_batches_sequence(
                app_name,
                self._get_batch_index_interval(app_name, state)
                & portion.open(after, portion.inf),
            ),
            after,
            batches_sequence,
            batches_hash_set,
        )

        return batches_sequence

    def get_batch(self, app_name: str, batch_hash: str) -> Batch:
        """Get a batch by its hash."""
        if batch_hash in self.apps[app_name]["initialized_batches_map"]:
            return self.apps[app_name]["initialized_batches_map"][batch_hash]
        elif batch_hash in self.apps[app_name]["operational_batches_hash_index_map"]:
            return self._get_operational_batch_by_hash(app_name, batch_hash)
        return {}

    def get_still_sequenced_batches(self, app_name: str) -> list[Batch]:
        """Get batches that are not finalized based on the finalization time border."""
        border = int(time.time()) - zconfig.FINALIZATION_TIME_BORDER
        return [
            batch
            for batch in self._filter_operational_batches_sequence(
                app_name,
                self._get_batch_index_interval(
                    app_name, "sequenced", exclude_next_states=True
                ),
            )
            if batch["timestamp"] < border
        ]

    def init_batches(self, app_name: str, bodies: Iterable[str]) -> None:
        """Initialize batches of transactions with a given body."""
        if not bodies:
            return

        now = int(time.time())
        for body in bodies:
            batch_hash = utils.gen_hash(body)
            if not self._batch_exists(app_name, batch_hash):
                self.apps[app_name]["initialized_batches_map"][batch_hash] = {
                    "app_name": app_name,
                    "node_id": zconfig.NODE["id"],
                    "timestamp": now,
                    "state": "initialized",
                    "hash": batch_hash,
                    "body": body,
                }

    def get_last_operational_batch(
        self, app_name: str, state: OperationalState | None
    ) -> Batch:
        """Get the last batch for a given state."""
        match state:
            case "sequenced" | None:
                return self.apps[app_name]["last_sequenced_batch"]
            case "locked":
                return self.apps[app_name]["last_locked_batch"]
            case "finalized":
                return self.apps[app_name]["last_finalized_batch"]

    def sequencer_init_batches(
        self, app_name: str, initializing_batches: list[Batch]
    ) -> None:
        """Initialize and sequence batches."""
        if not initializing_batches:
            return

        last_sequenced_batch = self.apps[app_name]["last_sequenced_batch"]
        chaining_hash = last_sequenced_batch.get("chaining_hash", "")
        index = last_sequenced_batch.get("index", self._BEFORE_GLOBAL_FIRST_BATCH_INDEX)

        for batch in initializing_batches:
            if self._batch_exists(app_name, batch["hash"]):
                continue

            batch_hash = utils.gen_hash(batch["body"])
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

            self.apps[app_name]["operational_batches_sequence"].append(batch)
            self.apps[app_name]["operational_batches_hash_index_map"][batch_hash] = (
                batch["index"]
            )
            self.apps[app_name]["last_sequenced_batch"] = batch

    def upsert_sequenced_batches(
        self, app_name: str, sequenced_batches: list[Batch]
    ) -> None:
        """Upsert sequenced batches."""
        if not sequenced_batches:
            return

        chaining_hash = self.apps[app_name]["last_sequenced_batch"].get(
            "chaining_hash", ""
        )
        now = int(time.time())
        for batch in sequenced_batches:
            if chaining_hash or batch["index"] == self._GLOBAL_FIRST_BATCH_INDEX:
                chaining_hash = utils.gen_hash(chaining_hash + batch["hash"])
                if batch["chaining_hash"] != chaining_hash:
                    zlogger.warning(
                        f"Invalid chaining hash: expected {chaining_hash} got {batch['chaining_hash']}"
                    )
                    return

            batch["state"] = "sequenced"
            batch["timestamp"] = now

            self.apps[app_name]["initialized_batches_map"].pop(batch["hash"], None)
            self.apps[app_name]["operational_batches_sequence"].append(batch)
            self.apps[app_name]["operational_batches_hash_index_map"][batch["hash"]] = (
                batch["index"]
            )

        if chaining_hash:
            self.apps[app_name]["last_sequenced_batch"] = batch

    def lock_batches(self, app_name: str, signature_data: SignatureData) -> None:
        """Update batches to 'locked' state up to a specified index."""
        if signature_data["index"] <= self.apps[app_name]["last_locked_batch"].get(
            "index", self._BEFORE_GLOBAL_FIRST_BATCH_INDEX
        ):
            return

        if (
            signature_data["hash"]
            not in self.apps[app_name]["operational_batches_hash_index_map"]
        ):
            zlogger.warning(
                f"The locking {signature_data=} hash couldn't be found in the "
                "operational batches."
            )
            return

        for batch in self._filter_operational_batches_sequence(
            app_name,
            self._get_batch_index_interval(app_name, "finalized").complement()
            & portion.closed(self._GLOBAL_FIRST_BATCH_INDEX, signature_data["index"]),
        ):
            batch["state"] = "locked"

        target_batch = self._get_operational_batch_by_hash(
            app_name, signature_data["hash"]
        )
        target_batch["lock_signature"] = signature_data["signature"]
        target_batch["locked_nonsigners"] = signature_data["nonsigners"]
        target_batch["locked_tag"] = signature_data["tag"]
        self.apps[app_name]["last_locked_batch"] = target_batch
        if not self.apps[app_name]["last_sequenced_batch"]:
            self.apps[app_name]["last_sequenced_batch"] = target_batch

    def finalize_batches(self, app_name: str, signature_data: SignatureData) -> None:
        """Update batches to 'finalized' state up to a specified index and save snapshots."""
        if signature_data.get(
            "index", self._BEFORE_GLOBAL_FIRST_BATCH_INDEX
        ) <= self.apps[app_name]["last_finalized_batch"].get(
            "index", self._BEFORE_GLOBAL_FIRST_BATCH_INDEX
        ):
            return

        if (
            signature_data["hash"]
            not in self.apps[app_name]["operational_batches_hash_index_map"]
        ):
            zlogger.warning(
                f"The finalizing {signature_data=} hash couldn't be found in the "
                "operational batches."
            )
            return

        snapshot_indexes: list[int] = []
        for batch in self._filter_operational_batches_sequence(
            app_name,
            portion.closed(self._GLOBAL_FIRST_BATCH_INDEX, signature_data["index"]),
        ):
            batch["state"] = "finalized"
            if batch["index"] % zconfig.SNAPSHOT_CHUNK == 0:
                snapshot_indexes.append(batch["index"])

        target_batch = self._get_operational_batch_by_hash(
            app_name, signature_data["hash"]
        )
        target_batch["finalization_signature"] = signature_data["signature"]
        target_batch["finalized_nonsigners"] = signature_data["nonsigners"]
        target_batch["finalized_tag"] = signature_data["tag"]
        self.apps[app_name]["last_finalized_batch"] = target_batch

        for snapshot_index in snapshot_indexes:
            if snapshot_index <= self._last_saved_index:
                continue
            self._last_saved_index = snapshot_index
            self._save_finalized_chunk_then_prune(app_name, snapshot_index)

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
            node_info
            for address, node_info in self.apps[app_name]["nodes_state"].items()
            if address in list(zconfig.NODES.keys())
        ]

    def upsert_locked_sync_point(
        self, app_name: str, signature_data: SignatureData
    ) -> None:
        """Upsert the locked sync point for an app."""
        self.apps[app_name]["nodes_state"]["locked_sync_point"] = {
            "index": signature_data["index"],
            "chaining_hash": signature_data["chaining_hash"],
            "hash": signature_data["hash"],
            "signature": signature_data["signature"],
            "nonsigners": signature_data["nonsigners"],
            "tag": signature_data["tag"],
        }

    def upsert_finalized_sync_point(
        self, app_name: str, signature_data: SignatureData
    ) -> None:
        """Upsert the finalized sync point for an app."""
        self.apps[app_name]["nodes_state"]["finalized_sync_point"] = {
            "index": signature_data["index"],
            "chaining_hash": signature_data["chaining_hash"],
            "hash": signature_data["hash"],
            "signature": signature_data["signature"],
            "nonsigners": signature_data["nonsigners"],
            "tag": signature_data["tag"],
        }

    def get_locked_sync_point(self, app_name: str) -> dict[str, Any]:
        """Get the locked sync point for an app."""
        return self.apps[app_name]["nodes_state"].get("locked_sync_point", {})

    def get_finalized_sync_point(self, app_name: str) -> dict[str, Any]:
        """Get the finalized sync point for an app."""
        return self.apps[app_name]["nodes_state"].get("finalized_sync_point", {})

    def add_missed_batches(
        self, app_name: str, missed_batches: Iterable[Batch]
    ) -> None:
        """Add missed batches."""
        self.apps[app_name]["missed_batches_map"].update(
            self._generate_batches_map(missed_batches)
        )

    def set_missed_batches(
        self, app_name: str, missed_batches: Iterable[Batch]
    ) -> None:
        """set missed batches."""
        self.apps[app_name]["missed_batches_map"] = self._generate_batches_map(
            missed_batches
        )

    def clear_missed_batches(self, app_name: str) -> None:
        """Empty missed batches."""
        self.apps[app_name]["missed_batches_map"] = {}

    def get_missed_batches_map(self, app_name: str) -> dict[str, Batch]:
        """Get missed batches."""
        return self.apps[app_name]["missed_batches_map"]

    def has_missed_batches(self) -> bool:
        """Check if there are missed batches across any app."""
        return any(
            self.apps[app_name]["missed_batches_map"]
            # TODO: Why not simply iterate through the apps?
            for app_name in list(zconfig.APPS.keys())
        )

    def reset_not_finalized_batches_timestamps(self, app_name: str) -> None:
        resetting_batches = itertools.chain(
            self.apps[app_name]["initialized_batches_map"].values(),
            self._filter_operational_batches_sequence(
                app_name,
                self._get_batch_index_interval(app_name, "finalized").complement(),
            ),
        )
        now = int(time.time())
        for batch in resetting_batches:
            batch["timestamp"] = now

    def reinitialize(
        self,
        app_name: str,
        new_sequencer_id: str,
        all_nodes_last_finalized_batch: Batch,
    ) -> None:
        """Reinitialize the database after a switch in the sequencer."""
        # TODO: Should get the batches from other nodes if they are missing.
        self.finalize_batches(
            app_name,
            signature_data={
                "index": all_nodes_last_finalized_batch["index"],
                "chaining_hash": all_nodes_last_finalized_batch["chaining_hash"],
                "hash": all_nodes_last_finalized_batch["hash"],
                "signature": all_nodes_last_finalized_batch["finalization_signature"],
                "nonsigners": all_nodes_last_finalized_batch["finalized_nonsigners"],
                "tag": all_nodes_last_finalized_batch["finalized_tag"],
            },
        )

        if zconfig.NODE["id"] == new_sequencer_id:
            self._resequence_batches(app_name, all_nodes_last_finalized_batch)
        else:
            self._reinitialize_batches(app_name, all_nodes_last_finalized_batch)

        self.apps[app_name]["nodes_state"] = {}
        self.apps[app_name]["missed_batches_map"] = {}

    def _resequence_batches(
        self, app_name: str, all_nodes_last_finalized_batch: Batch
    ) -> None:
        """Resequence batches after a switch in the sequencer."""
        index = all_nodes_last_finalized_batch.get(
            "index", self._BEFORE_GLOBAL_FIRST_BATCH_INDEX
        )
        chaining_hash = all_nodes_last_finalized_batch.get("chaining_hash", "")
        resequencing_batches = itertools.chain(
            self._filter_operational_batches_sequence(
                app_name,
                # TODO: I guess we should resequence all batches until the index of
                # the last finalized batch across all nodes instead of all locally
                # non-finalized batches, as the fully finalized batch across all nodes
                # may differ from the local last finalized batch.
                self._get_batch_index_interval(app_name, "finalized").complement(),
            ),
            self.apps[app_name]["initialized_batches_map"].values(),
        )
        resequenced_batches: list[Batch] = []
        for resequencing_batch in resequencing_batches:
            index += 1
            chaining_hash = utils.gen_hash(chaining_hash + resequencing_batch["hash"])
            resequenced_batch: Batch = {
                "app_name": resequencing_batch["app_name"],
                "node_id": resequencing_batch["node_id"],
                "timestamp": resequencing_batch["timestamp"],
                "hash": resequencing_batch["hash"],
                "body": resequencing_batch["body"],
                "index": index,
                "state": "sequenced",
                "chaining_hash": chaining_hash,
            }
            resequenced_batches.append(resequenced_batch)
            self.apps[app_name]["operational_batches_hash_index_map"][
                resequenced_batch["hash"]
            ] = index

        self.apps[app_name]["initialized_batches_map"] = {}
        self.apps[app_name]["operational_batches_sequence"] = (
            self._filter_operational_batches_sequence(
                app_name, self._get_batch_index_interval(app_name, "finalized")
            )
            + resequenced_batches
        )
        if resequenced_batches:
            self.apps[app_name]["last_sequenced_batch"] = resequenced_batches[-1]
        else:
            self.apps[app_name]["last_sequenced_batch"] = all_nodes_last_finalized_batch
        self.apps[app_name]["last_locked_batch"] = all_nodes_last_finalized_batch
        self.apps[app_name]["last_finalized_batch"] = all_nodes_last_finalized_batch

    def _reinitialize_batches(
        self, app_name: str, all_nodes_last_finalized_batch: Batch
    ) -> None:
        """Reinitialize batches after a switch in the sequencer."""
        all_nodes_last_finalized_batch_index = all_nodes_last_finalized_batch.get(
            "index", self._BEFORE_GLOBAL_FIRST_BATCH_INDEX
        )
        for batch in self._filter_operational_batches_sequence(
            app_name, portion.open(all_nodes_last_finalized_batch_index, portion.inf)
        ):
            reinitialized_batch: Batch = {
                "app_name": batch["app_name"],
                "node_id": batch["node_id"],
                "timestamp": batch["timestamp"],
                "hash": batch["hash"],
                "body": batch["body"],
                "state": "initialized",
            }
            self.apps[app_name]["initialized_batches_map"][
                batch["hash"]
            ] = reinitialized_batch
            self.apps[app_name]["operational_batches_hash_index_map"].pop(batch["hash"])

        self.apps[app_name]["operational_batches_sequence"] = (
            self._filter_operational_batches_sequence(
                app_name,
                portion.closed(
                    self._GLOBAL_FIRST_BATCH_INDEX, all_nodes_last_finalized_batch_index
                ),
            )
        )
        self.apps[app_name]["last_sequenced_batch"] = all_nodes_last_finalized_batch
        self.apps[app_name]["last_locked_batch"] = all_nodes_last_finalized_batch
        self.apps[app_name]["last_finalized_batch"] = all_nodes_last_finalized_batch

    # TODO: This function should be removed as it contains many duplicate
    # implementations with other BatchesSequence methods in this class.
    def _append_unique_batches_after_index(
        self,
        source_batches_sequence: list[Batch],
        after: int,
        # TODO: In Python, it's very unusual to use parameters as the output of
        # a function.
        target_batches_sequence: list[Batch],
        target_batches_hash_set: set[str],
    ) -> None:
        """Filter and add batches to the result based on index."""
        if not source_batches_sequence:
            return

        first_batch_index = source_batches_sequence[0]["index"]
        relative_after = after - first_batch_index

        for batch in source_batches_sequence[relative_after + 1 :]:
            if len(target_batches_sequence) >= zconfig.API_BATCHES_LIMIT:
                break

            if batch["hash"] in target_batches_hash_set:
                continue

            target_batches_sequence.append(batch)
            target_batches_hash_set.add(batch["hash"])

    def _filter_operational_batches_sequence(
        self,
        app_name: str,
        index_interval: portion.Interval,
    ) -> list[Batch]:
        if index_interval.empty:
            return []

        relative_index_calculator = self._generate_relative_index_calculator(app_name)
        relative_index_interval = index_interval.apply(
            lambda x: x.replace(
                lower=(
                    x.lower
                    if x.lower == -portion.inf
                    else relative_index_calculator(x.lower)
                ),
                upper=(
                    x.upper
                    if x.upper == portion.inf
                    else relative_index_calculator(x.upper)
                ),
            )
        )

        feasible_relative_index_interval = relative_index_interval & portion.closed(
            0, portion.inf
        )

        if not feasible_relative_index_interval.atomic:
            raise ValueError(
                f"The {feasible_relative_index_interval=} from "
                f"{relative_index_interval=} and {index_interval=} is not atomic."
            )

        closed_lower_relative_index = None
        if feasible_relative_index_interval.lower != 0:
            if relative_index_interval.left == portion.CLOSED:
                closed_lower_relative_index = feasible_relative_index_interval.lower
            else:
                closed_lower_relative_index = feasible_relative_index_interval.lower + 1

        open_upper_relative_index = None
        if feasible_relative_index_interval.upper != portion.inf:
            if feasible_relative_index_interval.right == portion.CLOSED:
                open_upper_relative_index = feasible_relative_index_interval.upper + 1
            else:
                open_upper_relative_index = feasible_relative_index_interval.upper

        return self.apps[app_name]["operational_batches_sequence"][
            closed_lower_relative_index:open_upper_relative_index
        ]

    def _get_operational_batch_by_hash(self, app_name: str, batch_hash: str) -> Batch:
        return self._get_operational_batch_by_index(
            app_name,
            self.apps[app_name]["operational_batches_hash_index_map"][batch_hash],
        )

    def _get_operational_batch_by_index(self, app_name: str, index: int) -> Batch:
        return self.apps[app_name]["operational_batches_sequence"][
            self._calculate_relative_index(app_name, index)
        ]

    def _batch_exists(self, app_name: str, batch_hash: str) -> bool:
        return (
            batch_hash in self.apps[app_name]["initialized_batches_map"]
            or batch_hash in self.apps[app_name]["operational_batches_hash_index_map"]
        )

    def _calculate_relative_index(self, app_name: str, index: int) -> int:
        return self._generate_relative_index_calculator(app_name)(index)

    def _generate_relative_index_calculator(
        self, app_name: str
    ) -> Callable[[int], int]:
        first_batch_index = self._get_first_batch_index(
            app_name, default=self._GLOBAL_FIRST_BATCH_INDEX
        )
        return lambda index: index - first_batch_index

    def _get_batch_index_interval(
        self,
        app_name: str,
        state: OperationalState | None = None,
        exclude_next_states: bool = False,
    ) -> portion.Interval:
        result = portion.closed(
            self._get_first_batch_index(
                app_name, state, default=self._GLOBAL_FIRST_BATCH_INDEX
            ),
            self._get_last_batch_index(
                app_name, state, default=self._BEFORE_GLOBAL_FIRST_BATCH_INDEX
            ),
        )

        if (
            state is not None
            and exclude_next_states
            and (next_state := self._get_next_operational_state(state))
        ):
            result -= self._get_batch_index_interval(
                app_name, next_state, exclude_next_states=False
            )

        return result

    def _get_first_batch_index(
        self,
        app_name: str,
        state: OperationalState | None = None,
        default: int = _NOT_SET_BATCH_INDEX,
    ) -> int:
        if not self._has_any_operational_batch(app_name, state):
            return default
        return self.apps[app_name]["operational_batches_sequence"][0]["index"]

    def _get_last_batch_index(
        self,
        app_name: str,
        state: OperationalState | None = None,
        default: int = _NOT_SET_BATCH_INDEX,
    ) -> int:
        if state is None:
            batches_sequence = self.apps[app_name]["operational_batches_sequence"]
            if batches_sequence:
                return batches_sequence[-1]["index"]
            else:
                return default
        else:
            return self.get_last_operational_batch(app_name, state).get(
                "index", default
            )

    def _has_any_operational_batch(
        self, app_name: str, state: OperationalState | None = None
    ) -> bool:
        return (
            self._get_last_batch_index(
                app_name, state, default=self._NOT_SET_BATCH_INDEX
            )
            != self._NOT_SET_BATCH_INDEX
        )

    @classmethod
    def _generate_batches_map(cls, batches: Iterable[Batch]) -> dict[str, Batch]:
        return {batch["hash"]: batch for batch in batches}

    @classmethod
    def _generate_batches_hash_index_map(
        cls, batches: Iterable[Batch]
    ) -> dict[str, int]:
        return {batch["hash"]: batch["index"] for batch in batches}

    @classmethod
    def _get_next_operational_state(
        cls, state: OperationalState
    ) -> OperationalState | None:
        match state:
            case "sequenced":
                return "locked"
            case "locked":
                return "finalized"
            case "finalized":
                return None


zdb = InMemoryDB()
