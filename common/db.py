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
from common import utils
from common.logger import zlogger
import itertools
from typing import TypedDict
from collections.abc import Iterable
from common.state import OperationalState
from common.batch import Batch, BatchRecord
from common.batch_sequence import BatchSequence


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
        self._last_saved_index = BatchSequence.BEFORE_GLOBAL_INDEX_OFFSET
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
                    "initialized_batch_map": {},
                    "operational_batch_sequence": BatchSequence(),
                    "operational_batch_hash_index_map": {},
                    "missed_batch_map": {},
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
            finalized_batch_sequence = cls._load_finalized_batch_sequence(app_name)
            result[app_name] = {
                "nodes_state": {},
                "initialized_batch_map": {},
                "operational_batch_sequence": finalized_batch_sequence,
                "operational_batch_hash_index_map": cls._generate_batch_hash_index_map(
                    finalized_batch_sequence
                ),
                "missed_batch_map": {},
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
    def _load_finalized_batch_sequence(
        cls, app_name: str, index: int | None = None
    ) -> BatchSequence:
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
            return BatchSequence()

        try:
            with gzip.open(
                snapshot_dir + f"/{str(effective_index).zfill(7)}.json.gz",
                "rt",
                encoding="UTF-8",
            ) as file:
                return BatchSequence.from_mapping(json.load(file))
        except (FileNotFoundError, EOFError):
            pass
        except (OSError, IOError, json.JSONDecodeError) as error:
            zlogger.error(
                "An error occurred while loading finalized batches for %s: %s",
                app_name,
            )
        return BatchSequence()

    def _save_finalized_chunk_then_prune(
        self, app_name: str, snapshot_index: int
    ) -> None:
        try:
            snapshot_border_index = max(
                snapshot_index - zconfig.SNAPSHOT_CHUNK,
                BatchSequence.BEFORE_GLOBAL_INDEX_OFFSET,
            )
            self._save_finalized_batches_chunk_to_file(
                app_name,
                border_index=snapshot_border_index,
                end_index=snapshot_index,
            )

            remove_border_index = max(
                snapshot_index - zconfig.SNAPSHOT_CHUNK * zconfig.REMOVE_CHUNK_BORDER,
                BatchSequence.BEFORE_GLOBAL_INDEX_OFFSET,
            )
            self._prune_old_finalized_batches(app_name, remove_border_index)
        except Exception as error:
            zlogger.error(
                "An error occurred while saving snapshot for %s at index %d: %s",
                app_name,
                snapshot_index,
            )

    def _save_finalized_batches_chunk_to_file(
        self, app_name: str, border_index: int, end_index: int
    ) -> None:
        snapshot_dir = os.path.join(zconfig.SNAPSHOT_PATH, zconfig.VERSION, app_name)
        with gzip.open(
            snapshot_dir + f"/{str(end_index).zfill(7)}.json.gz", "wt", encoding="UTF-8"
        ) as file:
            json.dump(
                self.apps[app_name]["operational_batch_sequence"]
                .filter(start_exclusive=border_index, end_inclusive=end_index)
                .to_mapping(),
                file,
            )

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

    def get_global_operational_batch_sequence(
        self,
        app_name: str,
        state: OperationalState = "sequenced",
        after: int = BatchSequence.BEFORE_GLOBAL_INDEX_OFFSET,
    ) -> BatchSequence:
        """Get batches filtered by state and optionally by index."""
        batch_sequence = BatchSequence(index_offset=after + 1)
        batch_hash_set: set[str] = set()  # TODO: Check if this is necessary.

        include_finalized_batches = state is None or state == "finalized"

        if include_finalized_batches:
            current_chunk = math.ceil((after + 1) / zconfig.SNAPSHOT_CHUNK)
            next_chunk = math.ceil(
                (after + 1 + zconfig.API_BATCHES_LIMIT) / zconfig.SNAPSHOT_CHUNK
            )
            finalized_chunk = math.ceil(
                self.apps[app_name][
                    "operational_batch_sequence"
                ].get_last_index_or_default("finalized")
                / zconfig.SNAPSHOT_CHUNK
            )

            if current_chunk != finalized_chunk:
                loaded_finalized_batches = self._load_finalized_batch_sequence(
                    app_name, after + 1
                )
                self._append_unique_batches_after_index(
                    loaded_finalized_batches,
                    after,
                    batch_sequence,
                    batch_hash_set,
                )

            if len(batch_sequence) < zconfig.API_BATCHES_LIMIT and next_chunk not in [
                current_chunk,
                finalized_chunk,
            ]:
                loaded_finalized_batches = self._load_finalized_batch_sequence(
                    app_name, after + 1 + len(batch_sequence)
                )
                self._append_unique_batches_after_index(
                    loaded_finalized_batches,
                    after,
                    batch_sequence,
                    batch_hash_set,
                )

        self._append_unique_batches_after_index(
            self.apps[app_name]["operational_batch_sequence"].filter(
                target_state=state,
                start_exclusive=after,
            ),
            after,
            batch_sequence,
            batch_hash_set,
        )

        return batch_sequence

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

    def finalize_batches(self, app_name: str, signature_data: SignatureData) -> None:
        """Update batches to 'finalized' state up to a specified index and save snapshots."""
        if signature_data.get(
            "index", BatchSequence.BEFORE_GLOBAL_INDEX_OFFSET
        ) <= self.apps[app_name][
            "operational_batch_sequence"
        ].get_last_index_or_default(
            "finalized", default=BatchSequence.BEFORE_GLOBAL_INDEX_OFFSET
        ):
            return

        if (
            signature_data["hash"]
            not in self.apps[app_name]["operational_batch_hash_index_map"]
        ):
            zlogger.warning(
                f"The finalizing {signature_data=} hash couldn't be found in the "
                "operational batches."
            )
            return

        snapshot_indexes: list[int] = []
        for index in (
            self.apps[app_name]["operational_batch_sequence"]
            .filter(exclude_state="finalized", end_inclusive=signature_data["index"])
            .indices()
        ):
            if index % zconfig.SNAPSHOT_CHUNK == 0:
                snapshot_indexes.append(index)

        target_batch = self._get_operational_batch_record_by_hash_or_empty(
            app_name, signature_data["hash"]
        ).get("batch", {})
        target_batch["finalization_signature"] = signature_data["signature"]
        target_batch["finalized_nonsigners"] = signature_data["nonsigners"]
        target_batch["finalized_tag"] = signature_data["tag"]
        self.apps[app_name]["operational_batch_sequence"].promote(
            last_index=signature_data["index"], target_state="finalized"
        )

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

    def _append_unique_batches_after_index(
        self,
        source_batch_sequence: BatchSequence,
        after: int,
        # TODO: In Python, it's very unusual to use parameters as the output of
        # a function.
        target_batch_sequence: BatchSequence,
        target_batches_hash_set: set[str],
    ) -> None:
        """Filter and add batches to the result based on index."""
        if not source_batch_sequence:
            return

        for batch in source_batch_sequence.filter(start_exclusive=after).batches():
            if len(target_batch_sequence) >= zconfig.API_BATCHES_LIMIT:
                break

            if batch["hash"] in target_batches_hash_set:
                continue

            target_batch_sequence.append(batch)
            target_batches_hash_set.add(batch["hash"])

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
