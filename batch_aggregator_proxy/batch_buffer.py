import asyncio
import logging
from collections import defaultdict

import httpx

from batch_aggregator_proxy.schema import ProxyConfig


class BatchBuffer:
    def __init__(self, config: ProxyConfig, logger: logging.Logger):
        """Initialize the buffer manager with the provided configuration."""
        self.logger = logger
        self.node_base_url = f"http://{config.NODE_HOST}:{config.NODE_PORT}"
        self.flush_volume = config.FLUSH_THRESHOLD_VOLUME
        self.buffers = defaultdict(lambda: asyncio.Queue())  # Async queue for each app_name
        self.locks = defaultdict(asyncio.Lock)  # Async lock for each app_name
        self.total_batches = 0  # Total number of batches across all buffers
        self.total_batches_lock = asyncio.Lock()  # Lock for protecting total_batches

    async def flush(self):
        """Flushes the buffer for all app_names asynchronously."""
        # Create a dictionary to hold all the batches for each app
        batches_mapping = {}

        for app_name, queue in self.buffers.items():
            async with self.locks[app_name]:
                if queue.empty():
                    continue

                buffer_data = []
                while not queue.empty():
                    buffer_data.append(await queue.get())

                batches_mapping[app_name] = buffer_data

        if not batches_mapping:
            return

        url = f"{self.node_base_url}/bulk-batches"

        async with httpx.AsyncClient() as client:
            try:
                response = await client.put(url, json=batches_mapping, headers={"Content-Type": "application/json"})
                response.raise_for_status()
                self.logger.info(f"Successfully sent batches for all apps: {len(batches_mapping)}.")
                # Reset total_batches after flushing
                async with self.total_batches_lock:
                    self.total_batches = 0
            except httpx.RequestError as e:
                self.logger.error(f"Error sending batches: {e}")

    async def add_batch(self, app_name: str, batch: str):
        """Adds a batch to the buffer for a specific app_name."""
        queue = self.buffers[app_name]
        await queue.put(batch)

        # Increment the total_batches count with lock to ensure thread-safety
        async with self.total_batches_lock:
            self.total_batches += 1

        # Check if total_batches exceeds the threshold and flush all if necessary
        if self.total_batches >= self.flush_volume:
            await self.flush()
