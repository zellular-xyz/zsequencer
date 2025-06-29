import asyncio
import bisect
import gzip
import json
import os
from typing import TypeAlias

from common.batch import get_batch_size_kb
from common.batch_sequence import BatchSequence
from common.logger import zlogger

# Type aliases for improved readability
ChunkFileInfo: TypeAlias = tuple[int, str]  # (start_index, filename)


class SnapshotManager:
    """Manages chunked snapshots of batch sequences for multiple applications."""

    def __init__(
        self,
        base_path: str,
        version: str,
        max_chunk_size_kb: float,
        app_names: list[str],
    ):
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
        self._max_chunk_size_kb = max_chunk_size_kb
        self._last_persisted_finalized_batch_index: dict[str, int | None] = {}

    async def initialize(self) -> None:
        for app_name in self._app_names:
            await self.initialize_app_storage(app_name)

    async def initialize_app_storage(self, app_name: str):
        """Initialize storage for an app by indexing its chunks and loading the last persisted state."""
        self._index_files(app_name=app_name)
        await self._load_last_batch_index(app_name=app_name)

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

    async def _load_last_batch_index(self, app_name: str):
        # Todo: prevent parsing chunk file for finding last batch index by tracking both start_index and end_index for chunks
        if len(self._app_name_to_chunks[app_name]) == 0:
            self._last_persisted_finalized_batch_index[app_name] = None
            return
        last_chunk_filename = self._app_name_to_chunks[app_name][-1][1]
        last_chunk_sequence = await self._load_file(
            app_name=app_name, file_name=last_chunk_filename
        )
        self._last_persisted_finalized_batch_index[app_name] = (
            last_chunk_sequence.get_last_index_or_default()
        )

    def get_last_batch_index(self, app_name: str) -> int | None:
        return self._last_persisted_finalized_batch_index[app_name]

    def _find_file_pos(self, app_name: str, batch_index: int) -> int:
        if app_name not in self._app_name_to_chunks:
            raise KeyError(f"App not found in indexed chunks: {app_name}")

        indexed_chunks = self._app_name_to_chunks[app_name]

        # Extract start indices for binary search
        return (
            bisect.bisect_right(indexed_chunks, batch_index, key=lambda row: row[0]) - 1
        )

    async def _load_file(self, app_name: str, file_name: str) -> BatchSequence:
        return await asyncio.to_thread(self._load_file_sync, app_name, file_name)

    def _load_file_sync(self, app_name: str, file_name: str) -> BatchSequence:
        zlogger.info(f"loading file {file_name=} for {app_name=}")
        file_path = os.path.join(self._get_app_storage_path(app_name), file_name)

        try:
            with gzip.open(file_path, "rt", encoding="UTF-8") as file:
                return BatchSequence.from_mapping(json.load(file))
        except (FileNotFoundError, EOFError):
            return BatchSequence()
        except (OSError, IOError, json.JSONDecodeError) as error:
            zlogger.error(
                "An error occurred while loading chunk for %s: %s", app_name, error
            )
            return BatchSequence()

    async def load_batches(
        self, app_name: str, after: int, retrieve_size_limit_kb: float | None = None
    ) -> BatchSequence:
        """
        Load all finalized batches for a given app from chunks after a given batch index.

        Args:
            app_name: Name of the app to load batches for
            after: Load batches after this index
            retrieve_size_limit_kb: Maximum size of batches to load in KB
        """
        if app_name not in self._app_name_to_chunks:
            raise KeyError(f"App not found in indexed chunks: {app_name}")

        file_pos = self._find_file_pos(app_name, 1 if after == 0 else after)
        if file_pos < 0:
            return BatchSequence()

        # Initialize result and size tracking
        merged_batches = BatchSequence()
        if retrieve_size_limit_kb is None:
            retrieve_size_limit_kb = float("inf")

        # Process chunks starting from the found position
        indexed_chunks = self._app_name_to_chunks[app_name][file_pos:]
        for _, file_name in indexed_chunks:
            chunk_sequence = (await self._load_file(app_name, file_name)).filter(
                start_exclusive=after
            )
            merged_batches.extend(chunk_sequence)

            # Check if we've reached the size limit
            if merged_batches.size_kb >= retrieve_size_limit_kb:
                break

        return merged_batches

    def _persist_batch_sequence(self, app_name: str, batches: BatchSequence):
        """Store a finalized batch sequence as a new chunk."""
        if not batches:
            return

        start_index = batches.get_first_index_or_default()
        chunk_filename = self._get_snapshot_filename(start_index)
        chunk_path = os.path.join(self._get_app_storage_path(app_name), chunk_filename)

        self._app_name_to_chunks[app_name].append((start_index, chunk_filename))
        self._last_persisted_finalized_batch_index[app_name] = (
            batches.get_last_index_or_default()
        )

        with gzip.open(chunk_path, "wt", encoding="UTF-8") as file:
            json.dump(batches.to_mapping(), file)

    def chunk_and_store_batch_sequence(self, app_name: str, batches: BatchSequence):
        # Calculate snapshot chunks based on size
        current_size = 0.0
        chunk_indices = []
        chunk_start = batches.index_offset

        for record in batches.records():
            batch_size = get_batch_size_kb(record["batch"])

            # If adding this batch would exceed size limit, create new chunk
            if current_size + batch_size > self._max_chunk_size_kb and current_size > 0:
                chunk_indices.append((chunk_start, record["index"] - 1))
                chunk_start = record["index"]
                current_size = batch_size
            else:
                current_size += batch_size

        for start_index, end_index in chunk_indices:
            self._persist_batch_sequence(
                app_name=app_name,
                batches=batches.filter(
                    start_exclusive=start_index - 1, end_inclusive=end_index
                ),
            )

    def get_latest_chunks_start_index(
        self, app_name: str, latest_chunks_count: int
    ) -> int:
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
            raise KeyError(f"App not found in indexed chunks: {app_name}")

        indexed_chunks = self._app_name_to_chunks[app_name]
        start_exclusive_index = BatchSequence.BEFORE_GLOBAL_INDEX_OFFSET

        if len(indexed_chunks) >= latest_chunks_count:
            start_exclusive_index = indexed_chunks[-latest_chunks_count][0]

        return start_exclusive_index

    async def load_latest_chunks(
        self, app_name: str, latest_chunks_count: int
    ) -> BatchSequence:
        start_exclusive_index = self.get_latest_chunks_start_index(
            app_name, latest_chunks_count
        )

        return await self.load_batches(app_name=app_name, after=start_exclusive_index)

    def _get_app_storage_path(self, app_name: str) -> str:
        return os.path.join(self._root_dir, app_name)

    def _get_snapshot_filename(self, start_index: int) -> str:
        return f"{str(start_index).zfill(12)}.json.gz"
