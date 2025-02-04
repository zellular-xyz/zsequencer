import threading
from collections import defaultdict

import requests
import uvicorn
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import JSONResponse

from batch_aggregator_proxy.schema import ProxyConfig


class BatchBuffer:
    def __init__(self, config: ProxyConfig):
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
        print(app_name, batch)
        with self.locks[app_name]:
            self.buffers[app_name].append(batch)

        if len(self.buffers[app_name]) >= self.flush_volume:
            self.flush(app_name)


class ProxyServer:
    def __init__(self, config: ProxyConfig):
        self.config = config
        self.node_base_url = f"http://{config.NODE_HOST}:{config.NODE_PORT}"
        self.app = FastAPI()
        self.buffer_manager = BatchBuffer(config)
        self.setup_routes()

    def setup_routes(self):
        # Define the /put_batch route
        self.app.add_api_route("/{app_name}/put_batch", self.put_batch, methods=["POST"])

        # Forward all other routes dynamically
        self.app.add_api_route("/{full_path:path}", self.forward_request,
                               methods=["GET", "POST", "PUT", "DELETE", "PATCH"])

    async def put_batch(self, app_name: str, batch: str = Form(...)):
        """Handles batch processing separately with an app_name."""
        if not app_name:
            raise HTTPException(status_code=400, detail="app_name is required")

        if not batch:
            raise HTTPException(status_code=400, detail="No batch provided")

        # Log and process the batch
        print(f"The batch is added. app: {app_name}, data length: {len(batch)}.")
        self.buffer_manager.add_batch(app_name=app_name, batch=batch)

        return {"message": "The batch is received successfully"}

    async def forward_request(self, full_path: str, request: Request):
        """Forwards all other requests to NODE_HOST:NODE_PORT."""
        target_url = f"{self.node_base_url}/{full_path}"

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

    def run(self):
        """Runs the FastAPI server with Uvicorn."""
        uvicorn.run(self.app, host=self.config.PROXY_HOST, port=self.config.PROXY_PORT)
