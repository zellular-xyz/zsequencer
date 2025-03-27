import bisect
import gzip
import json
import os
from typing import List, Dict, Tuple, Union

from common.batch_sequence import BatchSequence
from common.logger import zlogger


class StorageManager:

    def __init__(self,
                 snapshot_path: str,
                 version: str,
                 apps: list[str],
                 overlap_snapshot_counts: int):
        self._snapshots_dir = os.path.join(snapshot_path, version)
        self._indexed_files: Dict[str, List[Tuple[int, str]]] = {}
        self._apps = apps
        self._overlap_snapshot_counts = overlap_snapshot_counts
        self._last_persisted_finalized_batch_index: Dict[str, Union[int, None]] = {}
        self._initialize()

    def _initialize(self):
        for app_name in self._apps:
            self.handle_app(app_name)

    def handle_app(self, app_name: str):
        self._index_files(app_name=app_name)
        self._load_last_persisted_finalized_batch_index(app_name=app_name)

    def _index_files(self, app_name: str):
        snapshot_dir = self._get_app_storage_path(app_name=app_name)
        snapshot_filenames = sorted(
            file for file in os.listdir(snapshot_dir) if file.endswith(".json.gz")
        )
        app_indexed_files = []
        for snapshot_filename in snapshot_filenames:
            start_index = int(snapshot_filename.removesuffix(".json.gz"))
            app_indexed_files.append((start_index, snapshot_filename))
        self._indexed_files[app_name] = app_indexed_files

    def _load_last_persisted_finalized_batch_index(self, app_name: str):
        if len(self._indexed_files[app_name]) == 0:
            self._last_persisted_finalized_batch_index[app_name] = None
            return
        last_snapshot_filename = self._indexed_files[app_name][-1][1]
        last_snapshot_batch_sequence = self.load_file(app_name=app_name, file_name=last_snapshot_filename)
        self._last_persisted_finalized_batch_index[app_name] = last_snapshot_batch_sequence.get_last_index_or_default()

    def get_last_persisted_finalized_batch_index(self, app_name: str) -> Union[int, None]:
        return self._last_persisted_finalized_batch_index[app_name]

    def _find_file(self, app_name: str, batch_index: int) -> str | None:
        if app_name not in self._indexed_files:
            raise KeyError(f'App not found in indexed files {app_name}')

        indexed_files = self._indexed_files.get(app_name, [])
        if not indexed_files:
            return None

        # Extract start indices for binary search
        start_indices = [entry[0] for entry in indexed_files]

        # Find the rightmost index where batch_index can fit
        pos = bisect.bisect_right(start_indices, batch_index) - 1

        if pos < 0:
            return None  # No file contains this batch index

        return indexed_files[pos][1]

    def load_file(self, app_name: str, file_name: str) -> BatchSequence:
        file_path = os.path.join(self._get_app_storage_path(app_name), file_name)

        try:
            with gzip.open(file_path, "rt", encoding="UTF-8") as file:
                return BatchSequence.from_mapping(json.load(file))
        except (FileNotFoundError, EOFError):
            return BatchSequence()
        except (OSError, IOError, json.JSONDecodeError) as error:
            zlogger.error("An error occurred while loading finalized batches for %s: %s", app_name, error)

        return BatchSequence()

    def load_finalized_batches(self, app_name: str, after: int, retrieve_size_limit_kb: float = None) -> BatchSequence:
        """Load all finalized batches for a given app from the snapshot file after a given batch index."""
        if app_name not in self._indexed_files:
            raise KeyError(f'App not found in indexed files: {app_name}')

        indexed_files = self._indexed_files[app_name]
        if not indexed_files:
            return BatchSequence()

        # Extract start indices for binary search
        start_indices = [entry[0] for entry in indexed_files]

        # Find the leftmost file index that has batches after 'after'
        pos = bisect.bisect_right(start_indices, after)

        if pos >= len(indexed_files):
            return BatchSequence()  # No files contain batches beyond 'after'

        # Load and merge batch sequences from all relevant files
        merged_batches = BatchSequence()
        size_capacity = retrieve_size_limit_kb \
            if retrieve_size_limit_kb is not None else float('inf')  # No limit if None

        for _, file_name in indexed_files[pos:]:
            snapshot_batch_sequence = self.load_file(app_name, file_name).filter(start_exclusive=after)

            if retrieve_size_limit_kb is None:
                # No size limitation; take all batches
                sliced_batch_sequence = snapshot_batch_sequence
            else:
                # Apply size limitation
                sliced_batch_sequence = snapshot_batch_sequence.truncate_by_size(size_kb=size_capacity)

            contains_all_seq = sliced_batch_sequence.get_last_index_or_default() == snapshot_batch_sequence.get_last_index_or_default()
            merged_batches.extend(sliced_batch_sequence)
            size_capacity -= sliced_batch_sequence.size_kb

            if retrieve_size_limit_kb is not None and (not contains_all_seq or size_capacity <= 0):
                break

        return merged_batches

    def load_finalized_batch_sequence(
            self, app_name: str, index: int | None = None
    ) -> BatchSequence:
        if app_name not in self._indexed_files:
            raise KeyError(f'App not found in indexed files {app_name}')

        if index is None:
            snapshots = self._indexed_files[app_name]
            effective_index = int(snapshots[-1][0]) if snapshots else 0
        else:
            effective_index = index

        if effective_index <= 0:
            return BatchSequence()

        file_name = self._find_file(app_name, effective_index)
        return self.load_file(app_name=app_name, file_name=file_name)

    def store_finalized_batch_sequence(
            self, app_name: str, start_index: int, batches: BatchSequence
    ):
        snapshot_filename = self._get_snapshot_filename(start_index)
        snapshot_filepath = os.path.join(self._get_app_storage_path(app_name), snapshot_filename)
        self._indexed_files[app_name].append((start_index, snapshot_filename))
        self._last_persisted_finalized_batch_index[app_name] = batches.get_last_index_or_default()

        with gzip.open(
                snapshot_filepath, "wt", encoding="UTF-8"
        ) as file:
            json.dump(
                batches.to_mapping(),
                file,
            )

    def get_overlap_border_index(self, app_name: str) -> int:
        if app_name not in self._indexed_files:
            raise KeyError(f'App not found in indexed files {app_name}')

        indexed_files = self._indexed_files[app_name]
        if len(indexed_files) < self._overlap_snapshot_counts:
            return BatchSequence.BEFORE_GLOBAL_INDEX_OFFSET

        return indexed_files[-1 * self._overlap_snapshot_counts][0]

    def load_overlap_batch_sequence(self, app_name: str) -> BatchSequence:
        overlay_border_index = self.get_overlap_border_index(app_name)
        return self.load_finalized_batches(app_name=app_name, after=overlay_border_index)

    def _get_app_storage_path(self, app_name: str) -> str:
        return os.path.join(self._snapshots_dir, app_name)

    def _get_snapshot_filename(self, start_index: int) -> str:
        return f"{str(start_index).zfill(7)}.json.gz"
