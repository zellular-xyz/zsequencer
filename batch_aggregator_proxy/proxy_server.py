import threading
from collections import defaultdict
import requests
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from batch_aggregator_proxy.schema import ProxyConfig


class BatchBuffer:
    def __init__(self, config: ProxyConfig):
        """Initialize the buffer manager with the provided configuration."""
        self.node_base_url = f"http://{config.NODE_HOST}:{config.NODE_PORT}"
        self.flush_volume = config.FLUSH_THRESHOLD_VOLUME
        self.buffers = defaultdict(list)  # Separate buffer for each app_name
        self.locks = defaultdict(threading.Lock)  # Separate lock for each app_name

    def flush(self, app_name: str):
        """Flushes the buffer for a given app_name."""
        with self.locks[app_name]:
            if not self.buffers[app_name]:
                return

            buffer_data = self.buffers[app_name]
            self.buffers[app_name] = []  # Clear buffer after copying data

        url = f"{self.node_base_url}/node/{app_name}/bulk-batches"
        try:
            response = requests.put(url, json=buffer_data, headers={"Content-Type": "application/json"})
            response.raise_for_status()
            print(f"Successfully sent {len(buffer_data)} batches for app: {app_name}.")
        except requests.RequestException as e:
            print(f"Error sending batches for app {app_name}: {e}")

    def add_batch(self, app_name: str, batch: str):
        """Adds a batch to the buffer for a specific app_name."""
        with self.locks[app_name]:
            self.buffers[app_name].append(batch)

        # Flush buffer when the volume threshold is met
        if len(self.buffers[app_name]) >= self.flush_volume:
            self.flush(app_name)


app = FastAPI()
config = ProxyConfig.from_env()
buffer_manager = BatchBuffer(config)


@app.post("/{app_name}/put_batch")
async def put_batch(app_name: str, batch: str = Form(...)):
    """Handles batch processing with an app_name."""
    if not app_name or not batch:
        raise HTTPException(status_code=400, detail="Both app_name and batch are required")

    # Log and process the batch
    buffer_manager.add_batch(app_name=app_name, batch=batch)
    print(f"Received batch for app: {app_name}, data length: {len(batch)}.")

    return {"message": "The batch is received successfully"}


@app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def forward_request(full_path: str, request: Request):
    """Forwards requests to NODE_HOST:NODE_PORT."""
    target_url = f"{buffer_manager.node_base_url}/{full_path}"

    # Extract request data
    headers = dict(request.headers)
    query_params = request.query_params
    method = request.method
    body = await request.body()

    try:
        response = requests.request(
            method=method,
            url=target_url,
            headers=headers,
            params=query_params,
            data=body
        )
        return JSONResponse(content=response.json(), status_code=response.status_code)
    except requests.RequestException as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)

# if __name__ == "__main__":
#     uvicorn.run(app, host=config.PROXY_HOST, port=config.PROXY_PORT, workers=config.WORKERS_COUNT)
