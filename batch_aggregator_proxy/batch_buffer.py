import asyncio
import logging
from collections import defaultdict
from urllib.parse import urljoin

import httpx

from batch_aggregator_proxy.schema import ProxyConfig


class BatchBuffer:
    def __init__(self, config: ProxyConfig, logger: logging.Logger):
        """Initialize the buffer manager with the provided configuration."""
        self.logger = logger
        self.node_base_url = f"http://{config.NODE_HOST}:{config.NODE_PORT}"
        self.flush_volume = config.FLUSH_THRESHOLD_VOLUME  # Max buffer size before flush
        self.flush_interval = config.FLUSH_THRESHOLD_TIMEOUT  # Flush time threshold
        self.buffer_queue = asyncio.Queue()
        self._stop_event = asyncio.Event()
        self._flush_task = asyncio.create_task(self._periodic_flush())

    async def _periodic_flush(self):
        """Periodically flushes the buffer based on the timeout interval."""
        while not self._stop_event.is_set():
            await asyncio.sleep(self.flush_interval)
            await self.flush()

    async def flush(self):
        """Flush the buffer if it has items."""
        if self.buffer_queue.empty():
            return

        batches_mapping = defaultdict(list)
        batches_count = 0
        while not self.buffer_queue.empty() and batches_count <= self.flush_volume:
            app_name, batch = await self.buffer_queue.get()
            batches_mapping[app_name].append(batch)
            batches_count += 1

        url = urljoin(self.node_base_url, "node/bulk-batches")

        async with httpx.AsyncClient() as client:
            try:
                response = await client.put(url, json=batches_mapping, headers={"Content-Type": "application/json"})
                response.raise_for_status()
            except httpx.RequestError as e:
                self.logger.error(f"Error sending batches: {e}")
                for app_name, batches in batches_mapping.items():
                    for batch in batches:
                        await self.buffer_queue.put((app_name, batch))

    async def add_batch(self, app_name: str, batch: str):
        """Adds a batch to the buffer for a specific app_name and flushes if the volume exceeds the threshold."""
        await self.buffer_queue.put((app_name, batch))

        if self.buffer_queue.qsize() >= self.flush_volume:
            self.logger.info(
                f"Buffer size {self.buffer_queue.qsize()} reached threshold {self.flush_volume}, flushing.")
            await self.flush()

    async def shutdown(self):
        """Gracefully stops the periodic flush task."""
        self._stop_event.set()
        await self._flush_task
        await self.flush()  # Flush remaining items before exiting
