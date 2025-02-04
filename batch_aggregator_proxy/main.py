import os
import threading
from typing import List

import requests
from fastapi import FastAPI, Form, HTTPException


class Config:
    def __init__(self):
        self.NODE_BASE_URL = os.getenv("NODE_BASE_URL", "http://localhost:6001")
        self.APP_NAME = os.getenv("APP_NAME", "simple_app")
        self.FLUSH_THRESHOLD_VOLUME = int(os.getenv("FLUSH_THRESHOLD_VOLUME", 2000))


class BatchBuffer:
    def __init__(self, config: Config):
        self.node_base_url = config.NODE_BASE_URL
        self.app_name = config.APP_NAME
        self.flush_volume = config.FLUSH_THRESHOLD_VOLUME
        self.buffer: List[str] = []
        self.lock = threading.Lock()
        self.running = True

    def flush(self):
        with self.lock:
            if not self.buffer:
                return

        url = f"{self.node_base_url}/node/{self.app_name}/bulk-batches"
        try:
            response = requests.put(url, json=self.buffer, headers={"Content-Type": "application/json"})
            response.raise_for_status()
            self.buffer.clear()
            print(f"Successfully sent {len(self.buffer)} batches.")
        except requests.RequestException as e:
            print(f"Error sending batches: {e}")

    def add_batch(self, batch: str):
        with self.lock:
            self.buffer.append(batch)
        if len(self.buffer) >= self.flush_volume:
            self.flush()


buffer_manager = BatchBuffer(Config())

app = FastAPI()


@app.post("/put_batch")
def put_batch(batch: str = Form(...)):
    if not batch:
        raise HTTPException(status_code=400, detail="No batch provided")

    buffer_manager.add_batch(batch)
    return {"message": "Batch received successfully"}
