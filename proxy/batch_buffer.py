import asyncio
import logging
from collections import defaultdict, deque
from urllib.parse import urljoin

import httpx


class BatchBuffer:
    def __init__(self, config, logger: logging.Logger):
        """Initialize the buffer manager with the provided configuration."""
        self._logger = logger
        self._node_base_url = f"http://{config.HOST}:{config.PORT}"
        self._flush_volume = config.PROXY_FLUSH_THRESHOLD_VOLUME  # Max buffer size before flush
        self._flush_interval = config.PROXY_FLUSH_THRESHOLD_TIMEOUT  # Flush time threshold
        self._buffer_queue = deque()  # Replacing asyncio.Queue with deque
        self._stop_event = False  # Replacing asyncio.Event with a bool
        self._flush_task = None

    async def _periodic_flush(self):
        """Periodically flushes the buffer based on the timeout interval."""
        while not self._stop_event:
            await asyncio.sleep(self._flush_interval)
            await self.flush()

    async def flush(self):
        """Flush the buffer if it has items."""
        if not self._buffer_queue:
            return

        batches_mapping = defaultdict(list)
        batches_count = 0

        while self._buffer_queue and batches_count <= self._flush_volume:
            app_name, batch = self._buffer_queue.popleft()  # Using deque.popleft() instead of queue.get_nowait()
            batches_mapping[app_name].append(batch)
            batches_count += 1

        url = urljoin(self._node_base_url, "node/batches")

        async with httpx.AsyncClient() as client:
            try:
                response = await client.put(url, json=batches_mapping, headers={"Content-Type": "application/json"})
                response.raise_for_status()
            except httpx.RequestError as e:
                self._logger.error(f"Error sending batches: {e}")
                for app_name, batches in batches_mapping.items():
                    for batch in batches:
                        self._buffer_queue.append((app_name, batch))  # Using deque.append() instead of await put()

    async def add_batch(self, app_name: str, batch: str):
        """Adds a batch to the buffer for a specific app_name and flushes if the volume exceeds the threshold."""
        self._buffer_queue.append((app_name, batch))  # Using deque.append() instead of await put()

        if len(self._buffer_queue) >= self._flush_volume:
            self._logger.info(
                f"Buffer size {len(self._buffer_queue)} reached threshold {self._flush_volume}, flushing.")
            await self.flush()

    async def start(self):
        """Explicitly start the background task for periodic flushing."""
        if self._flush_task is None:
            self._flush_task = asyncio.create_task(self._periodic_flush())

    async def shutdown(self):
        """Gracefully stops the periodic flush task."""
        self._stop_event = True  # Using a simple boolean flag
        if self._flush_task:
            await self._flush_task
        await self.flush()
