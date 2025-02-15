import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response

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
