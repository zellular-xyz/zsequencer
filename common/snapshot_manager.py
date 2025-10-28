import asyncio
import bisect
import gzip
import json
import os
from concurrent.futures import ProcessPoolExecutor
from typing import TypeAlias

from common.batch_sequence import BatchSequence
from common.logger import zlogger

# Type aliases for improved readability
ChunkFileInfo: TypeAlias = tuple[int, str]  # (start_index, filename)


class SnapshotManager:
    """Manages chunked snapshots of batch sequences for multiple applications."""

    # Shared process pool for gzip read/write
    _EXECUTOR = ProcessPoolExecutor(max_workers=2)

    def __init__(
        self,
        base_path: str,
        version: str,
        app_names: list[str],
    ):
        self._root_dir = os.path.join(base_path, version)
        self._app_name_to_chunks: dict[str, list[ChunkFileInfo]] = {}
        self._app_names = app_names
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

    def _write_gzip_sync(self, path: str, data: dict) -> None:
        """Write gzip file via temp file and rename to ensure atomic save."""
        tmp_path = f"{path}.tmp"
        with gzip.open(tmp_path, "wt", encoding="UTF-8") as f:
            json.dump(data, f)
        os.replace(tmp_path, path)  # atomic move

    def _read_gzip_sync(self, path: str) -> dict:
        with gzip.open(path, "rt", encoding="UTF-8") as f:
            return json.load(f)

    async def _gzip_write_async(self, path: str, data: dict) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self._EXECUTOR, self._write_gzip_sync, path, data)

    async def _gzip_read_async(self, path: str) -> dict:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._EXECUTOR, self._read_gzip_sync, path)

    async def _load_file(self, app_name: str, file_name: str) -> BatchSequence:
        """Load gzip chunk asynchronously using process pool."""
        zlogger.info(f"loading file {file_name=} for {app_name=}")
        file_path = os.path.join(self._get_app_storage_path(app_name), file_name)

        try:
            data = await self._gzip_read_async(file_path)
            return BatchSequence.from_mapping(data)
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

    def store_batch_sequence(self, app_name: str, batches: BatchSequence):
        if not batches:
            return

        start_index = batches.get_first_index_or_default()
        chunk_filename = self._get_snapshot_filename(start_index)
        chunk_path = os.path.join(self._get_app_storage_path(app_name), chunk_filename)

        self._app_name_to_chunks[app_name].append((start_index, chunk_filename))
        self._last_persisted_finalized_batch_index[app_name] = (
            batches.get_last_index_or_default()
        )

        zlogger.info(f"saving file {chunk_filename=} for {app_name=}")
        asyncio.create_task(self._gzip_write_async(chunk_path, batches.to_mapping()))

    def get_latest_chunks_start_index(
        self, app_name: str, latest_chunks_count: int
    ) -> int:
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
