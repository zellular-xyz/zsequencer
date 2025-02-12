import asyncio
import logging
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from urllib.parse import urljoin

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from pydantic import Field
from pydantic_settings import BaseSettings


class ProxyConfig(BaseSettings):
    PROXY_HOST: str = Field(default="0.0.0.0")
    PROXY_PORT: int = Field(default=7000)
    HOST: str = Field(default="localhost")
    PORT: int = Field(default=6000)
    PROXY_FLUSH_THRESHOLD_VOLUME: int = Field(default=2000)
    PROXY_FLUSH_THRESHOLD_TIMEOUT: float = Field(default=0.1)
    PROXY_WORKERS_COUNT: int = Field(default=4)

    class Config:
        env_prefix = "ZSEQUENCER_"


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


config = ProxyConfig()

logger = logging.getLogger("batch_buffer")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

buffer_manager = BatchBuffer(config, logger)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handles startup and shutdown events."""
    await buffer_manager.start()
    yield
    await buffer_manager.shutdown()


app = FastAPI(lifespan=lifespan)


@app.put("/node/{app_name}/batches")
async def put_batch(app_name: str, request: Request):
    """Handles batch processing with an app_name."""

    # FIXME: batch aggregator should reject accepting batches with invalid app_name
    if not app_name:
        raise HTTPException(status_code=400, detail="app_name is required")
    batch = (await request.body()).decode('utf-8')
    # Log and process the batch asynchronously
    await buffer_manager.add_batch(app_name=app_name, batch=batch)
    logger.info(f"Received batch for app: {app_name}, data length: {len(batch)}.")

    return {"message": "The batch is received successfully"}


@app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def forward_request(full_path: str, request: Request):
    """Forwards requests asynchronously to NODE_HOST:NODE_PORT and returns a JSON response."""
    target_url = f"{buffer_manager._node_base_url}/{full_path}"

    headers = dict(request.headers)
    query_params = request.query_params
    method = request.method
    body = await request.body()

    async with httpx.AsyncClient() as client:
        try:
            response = await client.request(
                method, target_url, headers=headers, content=body
            )
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
        except httpx.HTTPStatusError as e:
            return Response(
                content=e.response.content,
                status_code=e.response.status_code,
                headers=dict(e.response.headers)
            )
        except httpx.RequestError as e:
            return Response(
                content=str(e),
                status_code=500  # Internal server error in case of connection issues
            )
