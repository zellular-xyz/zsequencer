import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request

from batch_buffer import BatchBuffer
from configs import ProxyConfig, NodeConfig

proxy_config = ProxyConfig()
node_config = NodeConfig()

logger = logging.getLogger("batch_buffer")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

buffer_manager = BatchBuffer(proxy_config=proxy_config,
                             node_config=node_config,
                             logger=logger)


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
