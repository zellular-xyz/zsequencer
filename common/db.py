from __future__ import annotations

import itertools
import os
import threading
import time
from collections import deque
from collections.abc import Iterable
from threading import Thread
from typing import Any, TypeAlias, TypedDict

from common import utils
from common.batch import Batch, BatchRecord, get_batch_size_kb
from common.batch_sequence import BatchSequence
from common.bls import is_sync_point_signature_verified
from common.logger import zlogger
from common.snapshot_manager import SnapshotManager
from common.state import FinalizedState, OperationalState, SequencedState
from config import zconfig
from utils import get_file_content

TimestampedIndex: TypeAlias = tuple[int, int]


class App(TypedDict, total=False):
    # TODO: Annotate the keys and values.
    nodes_state: dict[str, Any]
    initialized_batch_map: dict[str, Batch]
    operational_batch_sequence: BatchSequence
    # TODO: Check if it's necessary.
    operational_batch_hash_index_map: dict[str, int]
    missed_batch_map: dict[str, Batch]
    latency_tracking_queue: deque[TimestampedIndex]


class SignatureData(TypedDict, total=False):
    index: int
    chaining_hash: str
    hash: str
    signature: str
    nonsigners: list[str]
    tag: int


class InMemoryDB:
    """In-memory database class to manage batches of transactions and states for apps."""

    # TODO: It seems that there are some possible race-condition situations where
    # multiple data structures are mutated together, or a chain of methods needs
    # to be called atomically.

    def __init__(self) -> None:
        """Initialize the InMemoryDB instance."""
        self.sequencer_put_batches_lock = threading.Lock()
        self.pause_node = threading.Event()
        self.is_sequencer_down = False
        self.is_node_reachable = True
        self._snapshot_manager = SnapshotManager(
            base_path=zconfig.SNAPSHOT_PATH,
            version=zconfig.VERSION,
            max_chunk_size_kb=zconfig.SNAPSHOT_CHUNK_SIZE_KB,
            app_names=list(zconfig.APPS.keys()),
        )
        self.apps = self._load_finalized_batches_for_all_apps()
        self._fetching_thread = Thread(
            target=self._fetch_apps_and_network_state_periodically,
        )
        self._fetching_thread.start()

    def track_sequencing_indices(
        self,
        app_name: str,
        state: SequencedState | FinalizedState,
        last_index: int,
        current_time: int,
    ):
        """Track when a range of batches transitions to a new state and remove from previous state.

        Args:
            app_name: Name of the app to track state for
            state: Target operational state
            last_index: new last index committed at the state
            current_time: Current timestamp
        """
        queue = self.apps[app_name]["latency_tracking_queue"]
        if state == "sequenced":
            if len(queue) == 0 or queue[-1][1] < last_index:
                queue.append((current_time, last_index))
            return

        while queue and queue[0][1] <= last_index:
            queue.popleft()

    def has_delayed_batches(self) -> bool:
        current_time = int(time.time())
        for app_name in self.apps:
            queue = self.apps[app_name]["latency_tracking_queue"]
            if (
                len(queue) > 0
                and queue[0][0] < current_time - zconfig.FINALIZATION_TIME_BORDER
            ):
                return True
        return False

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
                    "initialized_batch_map": {},
                    "operational_batch_sequence": BatchSequence(),
                    "operational_batch_hash_index_map": {},
                    "missed_batch_map": {},
                    "latency_tracking_queue": deque(),
                }
                self._snapshot_manager.initialize_app_storage(app_name)
        zconfig.APPS.update(data)
        self.apps.update(new_apps)
        for app_name in zconfig.APPS:
            snapshot_path = os.path.join(
                zconfig.SNAPSHOT_PATH,
                zconfig.VERSION,
                app_name,
            )
            os.makedirs(snapshot_path, exist_ok=True)

    def _fetch_apps_and_network_state_periodically(self) -> None:
        """Periodically fetches apps and nodes data."""
        while True:
            try:
                self._fetch_apps()
            except Exception:
                zlogger.error("An unexpected error occurred while fetching apps data.")

            try:
                zconfig.fetch_network_state()
            except Exception:
                zlogger.error(
                    "An unexpected error occurred while fetching network state.",
                )

            time.sleep(zconfig.FETCH_APPS_AND_NODES_INTERVAL)

    def _load_finalized_batches_for_all_apps(self) -> dict[str, App]:
        """Load and return the initial state from the snapshot files."""
        result: dict[str, App] = {}

        # TODO: Replace with dot operator.
        for app_name in getattr(zconfig, "APPS", []):
            finalized_batch_sequence = self._snapshot_manager.load_latest_chunks(
                app_name=app_name, latest_chunks_count=zconfig.REMOVE_CHUNK_BORDER
            )
            result[app_name] = {
                "nodes_state": {},
                "initialized_batch_map": {},
                "operational_batch_sequence": finalized_batch_sequence,
                "operational_batch_hash_index_map": self._generate_batch_hash_index_map(
                    finalized_batch_sequence
                ),
                "missed_batch_map": {},
                "latency_tracking_queue": deque(),
            }

        return result

    def get_limited_initialized_batch_map(
        self, app_name: str, max_size_kb: float
    ) -> dict[str, Batch]:
        initialized_batch_map = self.get_batch_map(app_name=app_name)
        total_batches_size = 0.0
        limited_batch_map = {}
        for batch_hash, batch in initialized_batch_map.items():
            batch_size = get_batch_size_kb(batch)
            if total_batches_size + batch_size > max_size_kb:
                break
            limited_batch_map[batch_hash] = batch
            total_batches_size += batch_size
        return limited_batch_map

    def _prune_old_finalized_batches(self, app_name: str) -> None:
        remove_border_index = self._snapshot_manager.get_latest_chunks_start_index(
            app_name=app_name, latest_chunks_count=zconfig.REMOVE_CHUNK_BORDER
        )

        self.apps[app_name]["operational_batch_sequence"] = self.apps[app_name][
            "operational_batch_sequence"
        ].filter(start_exclusive=remove_border_index)
        self.apps[app_name]["operational_batch_hash_index_map"] = (
            self._generate_batch_hash_index_map(
                self.apps[app_name]["operational_batch_sequence"],
            )
        )

    def get_batch_map(self, app_name: str) -> dict[str, Batch]:
        # NOTE: We copy the dictionary in order to make it safe to work on it
        # without the fear of change in the middle of processing.
        return self.apps[app_name]["initialized_batch_map"].copy()

    def _get_first_finalized_batch(self, app_name: str) -> int:
        return self.apps[app_name][
            "operational_batch_sequence"
        ].get_first_index_or_default("finalized")

    def get_global_operational_batch_sequence(
        self,
        app_name: str,
        state: OperationalState = "sequenced",
        after: int = BatchSequence.BEFORE_GLOBAL_INDEX_OFFSET,
    ) -> BatchSequence:
        """
        Get batches filtered by state and optionally by index, combining storage and memory data.

        Args:
            app_name: Name of the app to get batches for
            state: Target operational state
            after: Starting index (exclusive)
        """
        size_limit = zconfig.node_receive_limit_per_window_size_kb
        remaining_size = size_limit
        result = BatchSequence()

        # Get batches from storage if needed
        first_memory_index = self._get_first_finalized_batch(app_name)
        while after + 1 < first_memory_index:
            result.extend(
                self._snapshot_manager.load_batches(
                    app_name=app_name,
                    after=after,
                    retrieve_size_limit_kb=remaining_size,
                )
            )
            # Return if result passes size_limit
            if result.size_kb >= size_limit:
                return result.truncate_by_size(size_kb=size_limit).filter(
                    target_state=state
                )

            remaining_size = size_limit - result.size_kb
            after = result.get_last_index_or_default()
            first_memory_index = self._get_first_finalized_batch(app_name)

        # Get in-memory batches
        memory_sequence = (
            self.apps[app_name]["operational_batch_sequence"]
            .filter(start_exclusive=after, target_state=state)
            .truncate_by_size(size_kb=remaining_size)
        )

        # Combine sequences
        if result:
            result.extend(memory_sequence)
        else:
            result = memory_sequence

        return result

    def get_batch_record_by_hash_or_empty(
        self,
        app_name: str,
        batch_hash: str,
    ) -> BatchRecord:
        """Get a batch by its hash."""
        if batch_hash in self.apps[app_name]["initialized_batch_map"]:
            return {
                "batch": self.apps[app_name]["initialized_batch_map"][batch_hash],
                "index": BatchSequence.BEFORE_GLOBAL_INDEX_OFFSET,
                "state": "initialized",
            }
        return self._get_operational_batch_record_by_hash_or_empty(
            app_name,
            batch_hash,
        )

    def init_batches(self, app_name: str, bodies: Iterable[str]) -> None:
        """Initialize batches of transactions with a given body."""
        if not bodies:
            return

        for body in bodies:
            batch_hash = utils.gen_hash(body)
            if not self._batch_exists(app_name, batch_hash):
                self.apps[app_name]["initialized_batch_map"][batch_hash] = {
                    "app_name": app_name,
                    "node_id": zconfig.NODE["id"],
                    "hash": batch_hash,
                    "body": body,
                }

    def get_last_operational_batch_record_or_empty(
        self,
        app_name: str,
        state: OperationalState,
    ) -> BatchRecord:
        """Get the last batch view for a given state."""
        return self.apps[app_name]["operational_batch_sequence"].get_last_or_empty(
            state,
        )

    def sequencer_init_batches(
        self,
        app_name: str,
        initializing_batches: list[Batch],
    ) -> None:
        """Initialize and sequence batches."""
        if not initializing_batches:
            return

        last_sequenced_batch = (
            self.apps[app_name]["operational_batch_sequence"]
            .get_last_or_empty()
            .get("batch", {})
        )
        chaining_hash = last_sequenced_batch.get("chaining_hash", "")

        for batch in initializing_batches:
            if self._batch_exists(app_name, batch["hash"]):
                continue

            batch_hash = utils.gen_hash(batch["body"])
            if batch["hash"] != batch_hash:
                zlogger.warning(
                    f"Invalid batch hash: expected {batch_hash} got {batch['hash']}",
                )
                continue

            chaining_hash = utils.gen_hash(chaining_hash + batch_hash)
            batch.update(
                {
                    "chaining_hash": chaining_hash,
                },
            )

            batch_index = self.apps[app_name]["operational_batch_sequence"].append(
                batch,
            )
            self.apps[app_name]["operational_batch_hash_index_map"][batch_hash] = (
                batch_index
            )

    def insert_sequenced_batches(
        self,
        app_name: str,
        batches: list[Batch],
    ) -> bool:
        """Upsert sequenced batches."""
        if not batches:
            return True

        chaining_hash = (
            self.apps[app_name]["operational_batch_sequence"]
            .get_last_or_empty()
            .get("batch", {})
            .get("chaining_hash", "")
        )
        for batch in batches:
            chaining_hash = utils.gen_hash(chaining_hash + batch["hash"])
            if batch["chaining_hash"] != chaining_hash:
                zlogger.warning(
                    f"Invalid chaining hash: expected {chaining_hash} got {batch['chaining_hash']}",
                )
                return False

            self.apps[app_name]["initialized_batch_map"].pop(batch["hash"], None)
            batch_index = self.apps[app_name]["operational_batch_sequence"].append(
                batch,
            )
            self.apps[app_name]["operational_batch_hash_index_map"][batch["hash"]] = (
                batch_index
            )

        return True

    def lock_batches(self, app_name: str, signature_data: SignatureData) -> bool:
        """Update batches to 'locked' state up to a specified index."""
        if not is_sync_point_signature_verified(
            app_name=app_name,
            state="sequenced",
            index=signature_data.get("index"),
            batch_hash=signature_data.get("hash"),
            chaining_hash=signature_data.get("chaining_hash"),
            tag=signature_data.get("tag"),
            signature_hex=signature_data.get("signature"),
            nonsigners=signature_data.get("nonsigners"),
        ):
            return False

        if signature_data["index"] <= self.apps[app_name][
            "operational_batch_sequence"
        ].get_last_index_or_default(
            "locked",
            default=BatchSequence.BEFORE_GLOBAL_INDEX_OFFSET,
        ):
            return False

        if (
            signature_data["hash"]
            not in self.apps[app_name]["operational_batch_hash_index_map"]
        ):
            zlogger.warning(
                f"The locking {signature_data=} hash couldn't be found in the "
                "operational batches.",
            )
            return False

        target_batch = self._get_operational_batch_record_by_hash_or_empty(
            app_name,
            signature_data["hash"],
        ).get("batch", {})

        if signature_data["chaining_hash"] != target_batch["chaining_hash"]:
            zlogger.warning(
                "The chaining hash on the locking signature does not match the corrosponding batch"
                f"in the operational batches!\nSignature: {signature_data}\nBatch: {target_batch}"
            )
            return False

        target_batch["lock_signature"] = signature_data["signature"]
        target_batch["locked_nonsigners"] = signature_data["nonsigners"]
        target_batch["locked_tag"] = signature_data["tag"]
        self.apps[app_name]["operational_batch_sequence"].promote(
            last_index=signature_data["index"],
            target_state="locked",
        )
        return True

    def finalize_batches(self, app_name: str, signature_data: SignatureData) -> bool:
        """
        Update batches to 'finalized' state up to a specified index and save snapshots.
        Snapshots are created when accumulated batch sizes exceed SNAPSHOT_SIZE_KB.
        """
        if not is_sync_point_signature_verified(
            app_name=app_name,
            state="locked",
            index=signature_data.get("index"),
            batch_hash=signature_data.get("hash"),
            chaining_hash=signature_data.get("chaining_hash"),
            tag=signature_data.get("tag"),
            signature_hex=signature_data.get("signature"),
            nonsigners=signature_data.get("nonsigners"),
        ):
            return False

        signature_finalized_index = signature_data.get(
            "index", BatchSequence.BEFORE_GLOBAL_INDEX_OFFSET
        )
        last_finalized_index = self.apps[app_name][
            "operational_batch_sequence"
        ].get_last_index_or_default(
            "finalized", default=BatchSequence.BEFORE_GLOBAL_INDEX_OFFSET
        )

        # Skip if already finalized or batch not found
        if signature_finalized_index <= last_finalized_index:
            return False

        if (
            signature_data["hash"]
            not in self.apps[app_name]["operational_batch_hash_index_map"]
        ):
            zlogger.warning(
                f"The finalizing {signature_data=} hash couldn't be found in the operational batches."
            )
            return False

        # Update target batch with finalization data
        target_batch = self._get_operational_batch_record_by_hash_or_empty(
            app_name,
            signature_data["hash"],
        ).get("batch", {})
        if signature_data["chaining_hash"] != target_batch["chaining_hash"]:
            zlogger.warning(
                "The chaining hash on the finalizing signature does not match the corrosponding batch"
                f"in the operational batches!\nSignature: {signature_data}\nBatch: {target_batch}"
            )
            return False

        target_batch.update(
            {
                "finalization_signature": signature_data["signature"],
                "finalized_nonsigners": signature_data["nonsigners"],
                "finalized_tag": signature_data["tag"],
            }
        )

        # Promote batches to finalized state
        self.apps[app_name]["operational_batch_sequence"].promote(
            last_index=signature_finalized_index, target_state="finalized"
        )

        last_persisted_index = self._snapshot_manager.get_last_batch_index(app_name)
        fresh_finalized_sequence = self.apps[app_name][
            "operational_batch_sequence"
        ].filter(
            start_exclusive=last_persisted_index,
            end_inclusive=signature_finalized_index,
        )

        if fresh_finalized_sequence.size_kb < zconfig.SNAPSHOT_CHUNK_SIZE_KB:
            return True

        self._snapshot_manager.chunk_and_store_batch_sequence(
            app_name=app_name, batches=fresh_finalized_sequence
        )
        self._prune_old_finalized_batches(app_name)
        return True

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
        self,
        app_name: str,
        signature_data: SignatureData,
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
        self,
        app_name: str,
        signature_data: SignatureData,
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

    def get_locked_sync_point_or_empty(self, app_name: str) -> SignatureData:
        """Get the locked sync point for an app."""
        return self.apps[app_name]["nodes_state"].get("locked_sync_point", {})

    def get_finalized_sync_point_or_empty(self, app_name: str) -> SignatureData:
        """Get the finalized sync point for an app."""
        return self.apps[app_name]["nodes_state"].get("finalized_sync_point", {})

    def add_missed_batches(
        self,
        app_name: str,
        missed_batches: Iterable[Batch],
    ) -> None:
        """Add missed batches."""
        self.apps[app_name]["missed_batch_map"].update(
            self._generate_batch_map(missed_batches),
        )

    def set_missed_batches(
        self,
        app_name: str,
        missed_batches: Iterable[Batch],
    ) -> None:
        """Set missed batches."""
        self.apps[app_name]["missed_batch_map"] = self._generate_batch_map(
            missed_batches,
        )

    def clear_missed_batches(self, app_name: str) -> None:
        """Empty missed batches."""
        self.apps[app_name]["missed_batch_map"] = {}

    def get_missed_batch_map(self, app_name: str) -> dict[str, Batch]:
        """Get missed batches."""
        return self.apps[app_name]["missed_batch_map"]

    def get_limited_apps_missed_batches(self) -> dict[str, dict[str, Batch]]:
        apps_missed_batches: dict[str, Any] = {}
        for app_name in list(zconfig.APPS.keys()):
            app_missed_batches = self.get_missed_batch_map(app_name)
            if len(app_missed_batches) > 0:
                # Limit the number of batches for each app
                limited_app_missed_batches = dict(
                    list(app_missed_batches.items())[
                        : zconfig.MAX_MISSED_BATCHES_TO_PICK
                    ]
                )
                apps_missed_batches[app_name] = limited_app_missed_batches
        return apps_missed_batches

    def has_missed_batches(self) -> bool:
        """Check if there are missed batches across any app."""
        return any(
            self.apps[app_name]["missed_batch_map"]
            # TODO: Why not simply iterate through the apps?
            for app_name in list(zconfig.APPS.keys())
        )

    def reset_latency_queue(self, app_name: str) -> None:
        self.apps[app_name]["latency_tracking_queue"].clear()
        last_index = self.apps[app_name][
            "operational_batch_sequence"
        ].get_last_index_or_default()
        last_finalized_index = self.apps[app_name][
            "operational_batch_sequence"
        ].get_last_index_or_default(state="finalized")
        if last_index > last_finalized_index:
            self.track_sequencing_indices(
                app_name=app_name,
                state="sequenced",
                last_index=last_index,
                current_time=int(time.time()),
            )

    def reset_initialized_batches(self, app_name: str) -> None:
        """reset initialized batches after a switch for the new sequencer."""
        self.apps[app_name]["initialized_batch_map"] = {}

    def initialize_missing_batches(self, app_name: str):
        """Initialized missing batches."""
        missing_batches = self.apps[app_name]["missed_batch_map"]
        for batch_hash, batch in missing_batches.items():
            self.apps[app_name]["initialized_batch_map"][batch_hash] = batch
        self.apps[app_name]["missed_batch_map"] = {}

    def reinitialize_batches(self, app_name: str) -> None:
        """Reinitialize batches after a switch in the sequencer."""
        last_locked_index = (
            self.apps[app_name]["operational_batch_sequence"]
            .get_last_or_empty(state="locked")
            .get("index", BatchSequence.BEFORE_GLOBAL_INDEX_OFFSET)
        )
        for batch in (
            self.apps[app_name]["operational_batch_sequence"]
            .filter(start_exclusive=last_locked_index)
            .batches()
        ):
            reinitialized_batch: Batch = {
                "app_name": batch["app_name"],
                "node_id": batch["node_id"],
                "hash": batch["hash"],
                "body": batch["body"],
            }
            self.apps[app_name]["initialized_batch_map"][batch["hash"]] = (
                reinitialized_batch
            )
            self.apps[app_name]["operational_batch_hash_index_map"].pop(batch["hash"])

        self.apps[app_name]["operational_batch_sequence"] = self.apps[app_name][
            "operational_batch_sequence"
        ].filter(end_inclusive=last_locked_index)

    def _get_operational_batch_record_by_hash_or_empty(
        self,
        app_name: str,
        batch_hash: str,
    ) -> BatchRecord:
        return self.apps[app_name]["operational_batch_sequence"].get_or_empty(
            self.apps[app_name]["operational_batch_hash_index_map"].get(
                batch_hash,
                BatchSequence.BEFORE_GLOBAL_INDEX_OFFSET,
            ),
        )

    def _batch_exists(self, app_name: str, batch_hash: str) -> bool:
        return (
            batch_hash in self.apps[app_name]["initialized_batch_map"]
            or batch_hash in self.apps[app_name]["operational_batch_hash_index_map"]
        )

    @classmethod
    def _generate_batch_map(cls, batches: Iterable[Batch]) -> dict[str, Batch]:
        return {batch["hash"]: batch for batch in batches}

    @classmethod
    def _generate_batch_hash_index_map(cls, batches: BatchSequence) -> dict[str, int]:
        return {
            batch_record["batch"]["hash"]: batch_record["index"]
            for batch_record in batches.records()
        }


zdb = InMemoryDB()
