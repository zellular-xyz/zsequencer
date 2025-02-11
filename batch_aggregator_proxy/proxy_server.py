import logging

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from batch_aggregator_proxy.batch_buffer import BatchBuffer
from batch_aggregator_proxy.schema import ProxyConfig

app = FastAPI()
config = ProxyConfig.from_env()

logger = logging.getLogger("batch_buffer")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

buffer_manager = BatchBuffer(config, logger)


class BatchRequest(BaseModel):
    batch: str


@app.post("/{app_name}/put_batch")
async def put_batch(app_name: str, request: BatchRequest):
    """Handles batch processing with an app_name."""
    if not app_name or not request.batch:
        raise HTTPException(status_code=400, detail="Both app_name and batch are required")

    # Log and process the batch asynchronously
    await buffer_manager.add_batch(app_name=app_name, batch=request.batch)
    logger.info(f"Received batch for app: {app_name}, data length: {len(request.batch)}.")

    return {"message": "The batch is received successfully"}


@app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def forward_request(full_path: str, request: Request):
    """Forwards requests asynchronously to NODE_HOST:NODE_PORT and returns a JSON response."""
    target_url = f"{buffer_manager.node_base_url}/{full_path}"

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