from __future__ import annotations

import itertools
import os
import threading
import time
from collections.abc import Iterable
from threading import Thread
from typing import Any
from typing import TypedDict

from common import utils
from common.batch import Batch, BatchRecord, get_batch_size_kb
from common.batch_sequence import BatchSequence
from common.logger import zlogger
from common.state import OperationalState
from common.storage_manager import StorageManager
from config import zconfig
from utils import get_file_content


class App(TypedDict, total=False):
    # TODO: Annotate the keys and values.
    nodes_state: dict[str, Any]
    initialized_batch_map: dict[str, Batch]
    operational_batch_sequence: BatchSequence
    # TODO: Check if it's necessary.
    operational_batch_hash_index_map: dict[str, int]
    missed_batch_map: dict[str, Batch]


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
        self._storage_manager = StorageManager(snapshot_path=zconfig.SNAPSHOT_PATH,
                                               version=zconfig.VERSION,
                                               apps=list(zconfig.APPS.keys()),
                                               overlap_snapshot_counts=zconfig.REMOVE_CHUNK_BORDER)
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
                    "initialized_batch_map": {},
                    "operational_batch_sequence": BatchSequence(),
                    "operational_batch_hash_index_map": {},
                    "missed_batch_map": {},
                }
                self._storage_manager.handle_app(app_name)
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

    def _load_finalized_batches_for_all_apps(self) -> dict[str, App]:
        """Load and return the initial state from the snapshot files."""
        result: dict[str, App] = {}

        # TODO: Replace with dot operator.
        for app_name in getattr(zconfig, "APPS", []):
            finalized_batch_sequence = self._storage_manager.load_overlap_batch_sequence(app_name)
            result[app_name] = {
                "nodes_state": {},
                "initialized_batch_map": {},
                "operational_batch_sequence": finalized_batch_sequence,
                "operational_batch_hash_index_map": self._generate_batch_hash_index_map(
                    finalized_batch_sequence
                ),
                "missed_batch_map": {},
            }

        return result

    def _save_finalized_chunk_then_prune(
            self, app_name: str, start_exclusive: int, end_inclusive: int
    ) -> None:
        try:
            self._save_finalized_batches_chunk_to_file(
                app_name,
                start_exclusive=start_exclusive,
                end_inclusive=end_inclusive,
            )
            # Detect Pruning old finalized batches index based on overlap size between in_memory and disk batches
            remove_border_index = self._storage_manager.get_overlap_border_index(app_name)
            self._prune_old_finalized_batches(app_name, remove_border_index)
        except Exception as error:
            zlogger.error(
                "An error occurred while saving snapshot for %s from index %d to %d: %s",
                app_name,
                start_exclusive,
                end_inclusive,
                error,
            )

    def _save_finalized_batches_chunk_to_file(
        self, app_name: str, start_exclusive: int, end_inclusive: int
    ) -> None:
        batches = (self.apps[app_name]["operational_batch_sequence"]
                   .filter(start_exclusive=start_exclusive, end_inclusive=end_inclusive))
        self._storage_manager.store_finalized_batch_sequence(app_name=app_name,
                                                             batches=batches)

    def get_limited_initialized_batch_map(self, app_name: str, max_kb_size: float) -> dict[str, Batch]:
        # NOTE: We copy the dictionary in order to make it safe to work on it
        # without the fear of change in the middle of processing.
        initialized_batch_map = self.apps[app_name]["initialized_batch_map"].copy()
        total_batches_size = 0.0
        limited_batch_map = {}
        for batch_hash, batch in initialized_batch_map.items():
            batch_size = get_batch_size_kb(batch)
            if total_batches_size + batch_size > max_kb_size:
                break
            limited_batch_map[batch_hash] = batch
            total_batches_size += batch_size
        return limited_batch_map

    def _prune_old_finalized_batches(self, app_name: str, border_index: int) -> None:
        self.apps[app_name]["operational_batch_sequence"] = self.apps[app_name][
            "operational_batch_sequence"
        ].filter(start_exclusive=border_index)
        self.apps[app_name]["operational_batch_hash_index_map"] = (
            self._generate_batch_hash_index_map(
                self.apps[app_name]["operational_batch_sequence"]
            )
        )

    def get_batch_map(self, app_name: str) -> dict[str, Batch]:
        # NOTE: We copy the dictionary in order to make it safe to work on it
        # without the fear of change in the middle of processing.
        return self.apps[app_name]["initialized_batch_map"].copy()

    def _get_first_finalized_batch(self, app_name: str) -> int:
        return self.apps[app_name]["operational_batch_sequence"].get_first_index_or_default("finalized")

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
        size_limit = zconfig.node_receive_limit_size
        first_memory_index = self._get_first_finalized_batch(app_name)
        result = None

        # Get batches from storage if needed
        if after + 1 < first_memory_index:
            result = self._storage_manager.load_finalized_batches(
                app_name=app_name,
                after=after,
                retrieve_size_limit_kb=size_limit
            )
            # Return if storage data doesn't reach memory boundary
            if result.get_last_index_or_default() < first_memory_index - 1:
                return result.filter(target_state=state) if state == "finalized" else \
                    result.filter(exclude_state="sequenced") if state == "locked" else result

        # Calculate remaining size and starting point for memory data
        remaining_size = size_limit - (result.size_kb if result else 0)
        memory_start = result.get_last_index_or_default() if result else after

        # Get in-memory batches
        memory_sequence = self.apps[app_name]["operational_batch_sequence"].truncate_by_size(
            size_kb=remaining_size,
            after=memory_start
        )

        # Combine sequences
        if result:
            result.extend(memory_sequence)
        else:
            result = memory_sequence

        # Apply state filtering
        if state == "finalized":
            return result.filter(target_state="finalized")
        elif state == "locked":
            return result.filter(exclude_state="sequenced")
        return result

    def get_batch_record_by_hash_or_empty(
        self, app_name: str, batch_hash: str
    ) -> BatchRecord:
        """Get a batch by its hash."""
        if batch_hash in self.apps[app_name]["initialized_batch_map"]:
            return {
                "batch": self.apps[app_name]["initialized_batch_map"][batch_hash],
                "index": BatchSequence.BEFORE_GLOBAL_INDEX_OFFSET,
                "state": "initialized",
            }
        else:
            return self._get_operational_batch_record_by_hash_or_empty(
                app_name, batch_hash
            )

    def get_still_sequenced_batches(self, app_name: str) -> list[Batch]:
        """Get batches that are not finalized based on the finalization time border."""
        border = int(time.time()) - zconfig.FINALIZATION_TIME_BORDER
        return [
            batch
            for batch in self.apps[app_name]["operational_batch_sequence"]
            .filter(exclude_state="locked")
            .batches()
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
                self.apps[app_name]["initialized_batch_map"][batch_hash] = {
                    "app_name": app_name,
                    "node_id": zconfig.NODE["id"],
                    "timestamp": now,
                    "hash": batch_hash,
                    "body": body,
                }

    def get_last_operational_batch_record_or_empty(
        self, app_name: str, state: OperationalState
    ) -> BatchRecord:
        """Get the last batch view for a given state."""
        return self.apps[app_name]["operational_batch_sequence"].get_last_or_empty(
            state
        )

    def sequencer_init_batches(
        self, app_name: str, initializing_batches: list[Batch]
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
                    f"Invalid batch hash: expected {batch_hash} got {batch['hash']}"
                )
                continue

            chaining_hash = utils.gen_hash(chaining_hash + batch_hash)
            batch.update(
                {
                    "chaining_hash": chaining_hash,
                }
            )

            batch_index = self.apps[app_name]["operational_batch_sequence"].append(
                batch
            )
            self.apps[app_name]["operational_batch_hash_index_map"][
                batch_hash
            ] = batch_index

    def upsert_sequenced_batches(
        self,
        app_name: str,
        batches: list[Batch],
    ) -> None:
        """Upsert sequenced batches."""
        if not batches:
            return

        chaining_hash = (
            self.apps[app_name]["operational_batch_sequence"]
            .get_last_or_empty()
            .get("batch", {})
            .get("chaining_hash", "")
        )
        now = int(time.time())
        for batch in batches:
            chaining_hash = utils.gen_hash(chaining_hash + batch["hash"])
            if batch["chaining_hash"] != chaining_hash:
                zlogger.warning(
                    f"Invalid chaining hash: expected {chaining_hash} got {batch['chaining_hash']}"
                )
                return

            batch["timestamp"] = now

            self.apps[app_name]["initialized_batch_map"].pop(batch["hash"], None)
            batch_index = self.apps[app_name]["operational_batch_sequence"].append(
                batch
            )
            self.apps[app_name]["operational_batch_hash_index_map"][
                batch["hash"]
            ] = batch_index

    def lock_batches(self, app_name: str, signature_data: SignatureData) -> None:
        """Update batches to 'locked' state up to a specified index."""
        if signature_data["index"] <= self.apps[app_name][
            "operational_batch_sequence"
        ].get_last_index_or_default(
            "locked", default=BatchSequence.BEFORE_GLOBAL_INDEX_OFFSET
        ):
            return

        if (
            signature_data["hash"]
            not in self.apps[app_name]["operational_batch_hash_index_map"]
        ):
            zlogger.warning(
                f"The locking {signature_data=} hash couldn't be found in the "
                "operational batches."
            )
            return

        target_batch = self._get_operational_batch_record_by_hash_or_empty(
            app_name, signature_data["hash"]
        ).get("batch", {})
        target_batch["lock_signature"] = signature_data["signature"]
        target_batch["locked_nonsigners"] = signature_data["nonsigners"]
        target_batch["locked_tag"] = signature_data["tag"]
        self.apps[app_name]["operational_batch_sequence"].promote(
            last_index=signature_data["index"], target_state="locked"
        )

    def _get_app_operational_batches(self, app_name: str) -> BatchSequence:
        return self.apps[app_name]["operational_batch_sequence"]

    def finalize_batches(self, app_name: str, signature_data: SignatureData) -> None:
        """
        Update batches to 'finalized' state up to a specified index and save snapshots.
        Snapshots are created when accumulated batch sizes exceed SNAPSHOT_SIZE_KB.
        """
        signature_finalized_index = signature_data.get("index", BatchSequence.BEFORE_GLOBAL_INDEX_OFFSET)
        last_finalized_index = self._get_app_operational_batches(app_name) \
            .get_last_index_or_default("finalized", default=BatchSequence.BEFORE_GLOBAL_INDEX_OFFSET)

        # Skip if already finalized or batch not found
        if signature_finalized_index <= last_finalized_index:
            return

        if signature_data["hash"] not in self.apps[app_name]["operational_batch_hash_index_map"]:
            zlogger.warning(
                f"The finalizing {signature_data=} hash couldn't be found in the operational batches."
            )
            return

        # Get new batches to be finalized
        last_persisted_index = self._storage_manager.get_last_persisted_finalized_batch_index(app_name)
        new_finalized_sequence = self._get_app_operational_batches(app_name).filter(
            exclude_state="finalized",
            start_exclusive=last_persisted_index if last_persisted_index is not None else -1,
            end_inclusive=signature_finalized_index
        )

        # Calculate snapshot chunks based on size
        current_size = 0.0
        chunks = []
        chunk_start = 0 if last_persisted_index is None else last_persisted_index + 1

        for record in new_finalized_sequence.records():
            batch_size = get_batch_size_kb(record["batch"])

            # If adding this batch would exceed size limit, create new chunk
            if current_size + batch_size > zconfig.SNAPSHOT_CHUNK_SIZE_KB and current_size > 0:
                chunks.append((chunk_start, record["index"] - 1))
                chunk_start = record["index"]
                current_size = batch_size
            else:
                current_size += batch_size

        # Add final chunk if there are remaining batches
        if current_size > 0:
            chunks.append((chunk_start, signature_finalized_index))

        # Update target batch with finalization data
        target_batch = self._get_operational_batch_record_by_hash_or_empty(
            app_name, signature_data["hash"]
        ).get("batch", {})
        target_batch.update({
            "finalization_signature": signature_data["signature"],
            "finalized_nonsigners": signature_data["nonsigners"],
            "finalized_tag": signature_data["tag"]
        })

        # Promote batches to finalized state
        self.apps[app_name]["operational_batch_sequence"].promote(
            last_index=signature_finalized_index,
            target_state="finalized"
        )

        # Save and prune chunks
        for start_index, end_index in chunks:
            # For the first chunk when there's no previous persisted data, use -1 as start_exclusive
            start_exclusive = -1 if start_index == 0 else start_index - 1
            self._save_finalized_chunk_then_prune(app_name, start_exclusive, end_index)

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

    def get_locked_sync_point_or_empty(self, app_name: str) -> SignatureData:
        """Get the locked sync point for an app."""
        return self.apps[app_name]["nodes_state"].get("locked_sync_point", {})

    def get_finalized_sync_point_or_empty(self, app_name: str) -> SignatureData:
        """Get the finalized sync point for an app."""
        return self.apps[app_name]["nodes_state"].get("finalized_sync_point", {})

    def add_missed_batches(
        self, app_name: str, missed_batches: Iterable[Batch]
    ) -> None:
        """Add missed batches."""
        self.apps[app_name]["missed_batch_map"].update(
            self._generate_batch_map(missed_batches)
        )

    def set_missed_batches(
        self, app_name: str, missed_batches: Iterable[Batch]
    ) -> None:
        """set missed batches."""
        self.apps[app_name]["missed_batch_map"] = self._generate_batch_map(
            missed_batches
        )

    def clear_missed_batches(self, app_name: str) -> None:
        """Empty missed batches."""
        self.apps[app_name]["missed_batch_map"] = {}

    def get_missed_batch_map(self, app_name: str) -> dict[str, Batch]:
        """Get missed batches."""
        return self.apps[app_name]["missed_batch_map"]

    def get_apps_missed_batches(self) -> dict[str, dict[str, Batch]]:
        apps_missed_batches: dict[str, Any] = {}
        for app_name in list(zconfig.APPS.keys()):
            app_missed_batches = self.get_missed_batch_map(app_name)
            if len(app_missed_batches) > 0:
                apps_missed_batches[app_name] = app_missed_batches
        return apps_missed_batches

    def has_missed_batches(self) -> bool:
        """Check if there are missed batches across any app."""
        return any(
            self.apps[app_name]["missed_batch_map"]
            # TODO: Why not simply iterate through the apps?
            for app_name in list(zconfig.APPS.keys())
        )

    def reset_not_finalized_batches_timestamps(self, app_name: str) -> None:
        resetting_batches = itertools.chain(
            self.apps[app_name]["initialized_batch_map"].values(),
            self.apps[app_name]["operational_batch_sequence"]
            .filter(
                exclude_state="finalized",
            )
            .batches(),
        )
        now = int(time.time())
        for batch in resetting_batches:
            batch["timestamp"] = now

    def reinitialize(
        self,
        app_name: str,
        new_sequencer_id: str,
        all_nodes_last_finalized_batch_record: BatchRecord,
    ) -> None:
        """Reinitialize the database after a switch in the sequencer."""
        # TODO: Should get the batches from other nodes if they are missing.
        self.finalize_batches(
            app_name,
            signature_data={
                "index": all_nodes_last_finalized_batch_record["index"],
                "chaining_hash": all_nodes_last_finalized_batch_record["batch"][
                    "chaining_hash"
                ],
                "hash": all_nodes_last_finalized_batch_record["batch"]["hash"],
                "signature": all_nodes_last_finalized_batch_record["batch"][
                    "finalization_signature"
                ],
                "nonsigners": all_nodes_last_finalized_batch_record["batch"][
                    "finalized_nonsigners"
                ],
                "tag": all_nodes_last_finalized_batch_record["batch"]["finalized_tag"],
            },
        )

        if zconfig.NODE["id"] == new_sequencer_id:
            zlogger.info("This node is acting as the SEQUENCER. ID: %s", zconfig.NODE["id"])
            self._resequence_batches(
                app_name,
                all_nodes_last_finalized_batch_record,
            )
        else:
            self._reinitialize_batches(
                app_name, all_nodes_last_finalized_batch_record["index"]
            )

        self.apps[app_name]["nodes_state"] = {}
        self.apps[app_name]["missed_batch_map"] = {}

    def _resequence_batches(
        self,
        app_name: str,
        all_nodes_last_finalized_batch_record: BatchRecord,
    ) -> None:
        """Resequence batches after a switch in the sequencer."""
        chaining_hash = all_nodes_last_finalized_batch_record.get("batch", {}).get(
            "chaining_hash", ""
        )
        resequencing_batches = itertools.chain(
            self.apps[app_name]["operational_batch_sequence"]
            .filter(
                # TODO: I guess we should resequence all batches until the index of
                # the last finalized batch across all nodes instead of all locally
                # non-finalized batches, as the fully finalized batch across all nodes
                # may differ from the local last finalized batch.
                exclude_state="finalized"
            )
            .batches(),
            self.apps[app_name]["initialized_batch_map"].values(),
        )
        resequenced_batches_list: list[Batch] = []
        for resequencing_batch in resequencing_batches:
            chaining_hash = utils.gen_hash(chaining_hash + resequencing_batch["hash"])
            resequenced_batch: Batch = {
                "app_name": resequencing_batch["app_name"],
                "node_id": resequencing_batch["node_id"],
                "timestamp": resequencing_batch["timestamp"],
                "hash": resequencing_batch["hash"],
                "body": resequencing_batch["body"],
                "chaining_hash": chaining_hash,
            }
            resequenced_batches_list.append(resequenced_batch)

        self.apps[app_name]["initialized_batch_map"] = {}
        self.apps[app_name]["operational_batch_sequence"] = (
            self.apps[app_name]["operational_batch_sequence"].filter(
                target_state="finalized"
            )
            + resequenced_batches_list
        )
        self.apps[app_name]["operational_batch_hash_index_map"] = (
            self._generate_batch_hash_index_map(
                self.apps[app_name]["operational_batch_sequence"]
            )
        )

    def _reinitialize_batches(
        self, app_name: str, all_nodes_last_finalized_batch_index: int
    ) -> None:
        """Reinitialize batches after a switch in the sequencer."""
        for batch in (
            self.apps[app_name]["operational_batch_sequence"]
            .filter(start_exclusive=all_nodes_last_finalized_batch_index)
            .batches()
        ):
            reinitialized_batch: Batch = {
                "app_name": batch["app_name"],
                "node_id": batch["node_id"],
                "timestamp": batch["timestamp"],
                "hash": batch["hash"],
                "body": batch["body"],
            }
            self.apps[app_name]["initialized_batch_map"][
                batch["hash"]
            ] = reinitialized_batch
            self.apps[app_name]["operational_batch_hash_index_map"].pop(batch["hash"])

        self.apps[app_name]["operational_batch_sequence"] = self.apps[app_name][
            "operational_batch_sequence"
        ].filter(end_inclusive=all_nodes_last_finalized_batch_index)

    def _get_operational_batch_record_by_hash_or_empty(
        self, app_name: str, batch_hash: str
    ) -> BatchRecord:
        return self.apps[app_name]["operational_batch_sequence"].get_or_empty(
            self.apps[app_name]["operational_batch_hash_index_map"].get(
                batch_hash, BatchSequence.BEFORE_GLOBAL_INDEX_OFFSET
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
