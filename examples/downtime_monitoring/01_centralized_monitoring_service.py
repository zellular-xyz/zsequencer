import random
import time
import threading
import logging
from typing import Any
import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import uvicorn
from zellular import Zellular

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("downtime-monitoring")

# Node URL configuration
MONITORED_NODES = {
    "0xNodeA123": "http://localhost:8001",
    "0xNodeB456": "http://localhost:8002",
    "0xNodeC789": "http://localhost:8003",
}

REQUEST_TIMEOUT = 3
POLL_INTERVAL_SECONDS = 10

node_status: dict[str, str] = {addr: "up" for addr in MONITORED_NODES}

node_events: dict[str, list[dict[str, Any]]] = {
    addr: [{"state": "up", "timestamp": 0}] for addr in MONITORED_NODES
}

app = FastAPI()

def check_node_status(node_address: str, node_url: str) -> str:
    try:
        response = requests.get(f"{node_url}/health", timeout=REQUEST_TIMEOUT)
        return "up" if response.status_code == 200 else "down"
    except requests.RequestException:
        return "down"

def monitor_loop():
    while True:
        node_address = random.choice(list(MONITORED_NODES.keys()))
        node_url = MONITORED_NODES[node_address]

        new_state = check_node_status(node_address, node_url)
        last_state = node_status.get(node_address)

        if last_state != new_state:
            node_status[node_address] = new_state
            event = {
                "state": new_state,
                "timestamp": int(time.time())
            }
            node_events[node_address].append(event)
            logger.info(f"{node_address} ➔ {new_state}")
        else:
            logger.info(f"No change: {node_address} is {new_state}")

        time.sleep(POLL_INTERVAL_SECONDS)

def calculate_downtime(events: list[dict[str, Any]], from_ts: int, to_ts: int) -> int:
    interval_events = [e for e in events if from_ts <= e["timestamp"] <= to_ts]

    if not interval_events:
        starting_state = max(
            (e for e in events if e["timestamp"] < from_ts),
            key=lambda e: e["timestamp"]
        )["state"]
        return to_ts - from_ts if starting_state == "down" else 0

    downtime = 0
    down_since = from_ts

    for event in interval_events:
        if event["state"] == "down":
            down_since = event["timestamp"]
        elif event["state"] == "up":
            downtime += event["timestamp"] - down_since

    if interval_events[-1]["state"] == "down":
        downtime += to_ts - down_since

    return downtime

@app.get("/downtime")
def get_downtime(address: str, from_timestamp: int, to_timestamp: int):
    if address not in node_events:
        raise HTTPException(status_code=404, detail="Address not found")

    events = node_events[address]
    total_downtime = calculate_downtime(events, from_timestamp, to_timestamp)
    return JSONResponse({
        "address": address,
        "from_timestamp": from_timestamp,
        "to_timestamp": to_timestamp,
        "total_downtime_seconds": total_downtime
    })

if __name__ == "__main__":
    threading.Thread(target=monitor_loop, daemon=True).start()
    uvicorn.run(app, host="0.0.0.0", port=5000)
