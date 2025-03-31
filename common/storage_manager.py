import bisect
import gzip
import json
import os

from common.batch_sequence import BatchSequence
from common.logger import zlogger


class StorageManager:

    def __init__(self,
                 snapshot_path: str,
                 version: str,
                 app_names: list[str],
                 overlap_snapshot_counts: int):
        self._snapshots_dir = os.path.join(snapshot_path, version)
        self._app_name_to_start_index_filename_pairs: dict[str, list[tuple[int, str]]] = {}
        self._app_names = app_names
        self._overlap_snapshot_counts = overlap_snapshot_counts
        self._last_persisted_finalized_batch_index: dict[str, int | None] = {}
        self._initialize()

    def _initialize(self):
        for app_name in self._app_names:
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
        self._app_name_to_start_index_filename_pairs[app_name] = app_indexed_files

    def _load_last_persisted_finalized_batch_index(self, app_name: str):
        if len(self._app_name_to_start_index_filename_pairs[app_name]) == 0:
            self._last_persisted_finalized_batch_index[app_name] = None
            return
        last_snapshot_filename = self._app_name_to_start_index_filename_pairs[app_name][-1][1]
        last_snapshot_batch_sequence = self.load_file(app_name=app_name, file_name=last_snapshot_filename)
        self._last_persisted_finalized_batch_index[app_name] = last_snapshot_batch_sequence.get_last_index_or_default()

    def get_last_persisted_finalized_batch_index(self, app_name: str) -> int | None:
        return self._last_persisted_finalized_batch_index[app_name]

    def _find_file(self, app_name: str, batch_index: int) -> tuple[str | None, int | None]:
        """
        Find the file containing the batch_index and return its filename and position.
        Returns (None, None) if no suitable file is found.
        """
        if app_name not in self._app_name_to_start_index_filename_pairs:
            raise KeyError(f'App not found in indexed files {app_name}')

        indexed_files = self._app_name_to_start_index_filename_pairs[app_name]
        if not indexed_files:
            return None, None

        # Extract start indices for binary search
        start_indices = [entry[0] for entry in indexed_files]

        # Find the rightmost index where batch_index can fit
        pos = bisect.bisect_right(start_indices, batch_index) - 1

        if pos < 0:
            return None, None

        return indexed_files[pos][1], pos

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

    def load_finalized_batches(self, app_name: str, after: int,
                               retrieve_size_limit_kb: float | None = None) -> BatchSequence:
        """
        Load all finalized batches for a given app from the snapshot file after a given batch index.

        Args:
            app_name: Name of the app to load batches for
            after: Load batches after this index
            retrieve_size_limit_kb: Maximum size of batches to load in KB
        """
        if app_name not in self._app_name_to_start_index_filename_pairs:
            raise KeyError(f'App not found in indexed files: {app_name}')

        # Find the first file containing batches after the given index
        first_file, start_pos = self._find_file(app_name, after)
        if first_file is None or start_pos is None:
            return BatchSequence()

        # Initialize merge result and size tracking
        merged_batches = None
        size_capacity = retrieve_size_limit_kb if retrieve_size_limit_kb is not None else float('inf')
        indexed_files = self._app_name_to_start_index_filename_pairs[app_name]

        # Process files starting from the found position
        for _, file_name in indexed_files[start_pos:]:
            snapshot_batch_sequence = self.load_file(app_name, file_name).filter(start_exclusive=after)

            # Apply size limit if specified
            if retrieve_size_limit_kb is not None:
                sliced_batch_sequence = snapshot_batch_sequence.truncate_by_size(size_kb=size_capacity)
                contains_all_seq = (sliced_batch_sequence.get_last_index_or_default() ==
                                    snapshot_batch_sequence.get_last_index_or_default())
            else:
                sliced_batch_sequence = snapshot_batch_sequence
                contains_all_seq = True

            # Merge with existing batches
            if merged_batches is None:
                merged_batches = sliced_batch_sequence
            else:
                merged_batches.extend(sliced_batch_sequence)

            # Update remaining capacity and check if we should stop
            size_capacity -= sliced_batch_sequence.size_kb
            if not contains_all_seq or size_capacity <= 0:
                break

        return merged_batches if merged_batches is not None else BatchSequence()

    def store_finalized_batch_sequence(
            self, app_name: str, batches: BatchSequence
    ):
        start_index = batches.get_first_index_or_default()
        snapshot_filename = self._get_snapshot_filename(start_index)
        snapshot_filepath = os.path.join(self._get_app_storage_path(app_name), snapshot_filename)
        self._app_name_to_start_index_filename_pairs[app_name].append((start_index, snapshot_filename))
        self._last_persisted_finalized_batch_index[app_name] = batches.get_last_index_or_default()

        with gzip.open(
                snapshot_filepath, "wt", encoding="UTF-8"
        ) as file:
            json.dump(
                batches.to_mapping(),
                file,
            )

    def get_overlap_border_index(self, app_name: str) -> int:
        if app_name not in self._app_name_to_start_index_filename_pairs:
            raise KeyError(f'App not found in indexed files {app_name}')

        indexed_files = self._app_name_to_start_index_filename_pairs[app_name]
        if len(indexed_files) < self._overlap_snapshot_counts:
            return BatchSequence.BEFORE_GLOBAL_INDEX_OFFSET

        return indexed_files[-1 * self._overlap_snapshot_counts][0]

    def load_overlap_batch_sequence(self, app_name: str) -> BatchSequence:
        overlap_border_index = self.get_overlap_border_index(app_name)
        return self.load_finalized_batches(app_name=app_name, after=overlap_border_index)

    def _get_app_storage_path(self, app_name: str) -> str:
        return os.path.join(self._snapshots_dir, app_name)

    def _get_snapshot_filename(self, start_index: int) -> str:
        return f"{str(start_index).zfill(7)}.json.gz"
