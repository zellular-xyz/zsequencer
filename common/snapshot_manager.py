import bisect
import gzip
import json
import os
from typing import TypeAlias

from common.batch_sequence import BatchSequence
from common.logger import zlogger

# Type aliases for improved readability
ChunkFileInfo: TypeAlias = tuple[int, str]  # (start_index, filename)
IndexedChunk: TypeAlias = tuple[str, int]  # (filename, position)


class SnapshotManager:
    """Manages chunked snapshots of batch sequences for multiple applications."""

    def __init__(self,
                 base_path: str,
                 version: str,
                 app_names: list[str]):
        """
        Initialize the SnapshotManager.

        Args:
            base_path: Base directory path for storing snapshots
            version: Version identifier for the snapshot directory
            app_names: List of application names to manage
        """
        self._root_dir = os.path.join(base_path, version)
        self._app_name_to_chunks: dict[str, list[ChunkFileInfo]] = {}
        self._app_names = app_names
        self._last_persisted_finalized_batch_index: dict[str, int | None] = {}
        self._initialize()

    def _initialize(self):
        for app_name in self._app_names:
            self.initialize_app_storage(app_name)

    def initialize_app_storage(self, app_name: str):
        """Initialize storage for an app by indexing its chunks and loading the last persisted state."""
        self._index_files(app_name=app_name)
        self._load_last__batch_index(app_name=app_name)

    def _index_files(self, app_name: str):
        app_dir = self._get_app_storage_path(app_name=app_name)
        chunk_filenames = sorted(
            file for file in os.listdir(app_dir) if file.endswith(".json.gz")
        )
        indexed_chunks: list[ChunkFileInfo] = []
        for filename in chunk_filenames:
            start_index = int(filename.removesuffix(".json.gz"))
            indexed_chunks.append((start_index, filename))
        self._app_name_to_chunks[app_name] = indexed_chunks

    def _load_last__batch_index(self, app_name: str):
        # Todo: prevent parsing chunk file for finding last batch index by tracking both start_index and end_index for chunks
        if len(self._app_name_to_chunks[app_name]) == 0:
            self._last_persisted_finalized_batch_index[app_name] = None
            return
        last_chunk_filename = self._app_name_to_chunks[app_name][-1][1]
        last_chunk_sequence = self._load_file(app_name=app_name, file_name=last_chunk_filename)
        self._last_persisted_finalized_batch_index[app_name] = last_chunk_sequence.get_last_index_or_default()

    def get_last_batch_index(self, app_name: str) -> int | None:
        return self._last_persisted_finalized_batch_index[app_name]

    def _find_file(self, app_name: str, batch_index: int) -> IndexedChunk | None:
        if app_name not in self._app_name_to_chunks:
            raise KeyError(f'App not found in indexed chunks: {app_name}')

        indexed_chunks = self._app_name_to_chunks[app_name]
        if not indexed_chunks:
            return None

        # Extract start indices for binary search
        start_indices = [entry[0] for entry in indexed_chunks]
        pos = bisect.bisect_right(start_indices, batch_index) - 1

        if pos < 0:
            return None

        return (indexed_chunks[pos][1], pos)

    def _load_file(self, app_name: str, file_name: str) -> BatchSequence:
        file_path = os.path.join(self._get_app_storage_path(app_name), file_name)

        try:
            with gzip.open(file_path, "rt", encoding="UTF-8") as file:
                return BatchSequence.from_mapping(json.load(file))
        except (FileNotFoundError, EOFError):
            return BatchSequence()
        except (OSError, IOError, json.JSONDecodeError) as error:
            zlogger.error("An error occurred while loading chunk for %s: %s", app_name, error)
            return BatchSequence()

    def load_batches(self, app_name: str, after: int,
                     retrieve_size_limit_kb: float | None = None) -> BatchSequence:
        """
        Load all finalized batches for a given app from chunks after a given batch index.

        Args:
            app_name: Name of the app to load batches for
            after: Load batches after this index
            retrieve_size_limit_kb: Maximum size of batches to load in KB
        """
        if app_name not in self._app_name_to_chunks:
            raise KeyError(f'App not found in indexed chunks: {app_name}')

        found_file = self._find_file(app_name, after)
        if found_file is None:
            return BatchSequence()

        file_name, start_pos = found_file

        # Initialize result and size tracking
        merged_batches = BatchSequence()
        size_capacity = retrieve_size_limit_kb if retrieve_size_limit_kb is not None else float('inf')
        indexed_chunks = self._app_name_to_chunks[app_name]

        # Process chunks starting from the found position
        for _, file_name in indexed_chunks[start_pos:]:
            chunk_sequence = self._load_file(app_name, file_name).filter(start_exclusive=after)
            truncated_sequence = chunk_sequence.truncate_by_size(size_kb=size_capacity)

            merged_batches.extend(truncated_sequence)
            size_capacity -= truncated_sequence.size_kb

            # Check if we've reached the size limit
            if size_capacity <= 0:
                break

            # Check if we got all batches from the current chunk
            if truncated_sequence.get_last_index_or_default() < chunk_sequence.get_last_index_or_default():
                break

        return merged_batches

    def store_batch_sequence(self, app_name: str, batches: BatchSequence):
        """Store a finalized batch sequence as a new chunk."""
        if not batches:
            return

        start_index = batches.get_first_index_or_default()
        chunk_filename = self._get_snapshot_filename(start_index)
        chunk_path = os.path.join(self._get_app_storage_path(app_name), chunk_filename)

        self._app_name_to_chunks[app_name].append((start_index, chunk_filename))
        self._last_persisted_finalized_batch_index[app_name] = batches.get_last_index_or_default()

        with gzip.open(chunk_path, "wt", encoding="UTF-8") as file:
            json.dump(batches.to_mapping(), file)

    def get_latest_chunks_start_index(self, app_name: str, latest_chunks_count: int) -> int:
        """
        Get the starting index for loading the specified number of most recent chunks.

        Args:
            app_name: Name of the app to get the index for
            latest_chunks_count: Number of most recent chunks to consider

        Returns:
            The index where the latest chunks start, or BEFORE_GLOBAL_INDEX_OFFSET if not enough chunks

        Raises:
            KeyError: If app_name is not found in indexed chunks
        """
        if app_name not in self._app_name_to_chunks:
            raise KeyError(f'App not found in indexed chunks: {app_name}')

        indexed_chunks = self._app_name_to_chunks[app_name]
        start_exclusive_index = BatchSequence.BEFORE_GLOBAL_INDEX_OFFSET

        if len(indexed_chunks) >= latest_chunks_count:
            start_exclusive_index = indexed_chunks[-latest_chunks_count][0]

        return start_exclusive_index

    def load_latest_chunks(self, app_name: str, latest_chunks_count: int) -> BatchSequence:
        start_exclusive_index = self.get_latest_chunks_start_index(app_name, latest_chunks_count)

        return self.load_batches(app_name=app_name, after=start_exclusive_index)

    def _get_app_storage_path(self, app_name: str) -> str:
        return os.path.join(self._root_dir, app_name)

    def _get_snapshot_filename(self, start_index: int) -> str:
        return f"{str(start_index).zfill(7)}.json.gz"