import random
import time
import threading
import json
import logging
from typing import Any
import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import uvicorn
from zellular import Zellular, EigenlayerNetwork

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

# -- start: configuring eigenlayer network --
# Initialize Zellular client
network = EigenlayerNetwork(
    subgraph_url="https://api.studio.thegraph.com/query/95922/avs-subgraph/version/latest",
    threshold_percent=40
)
zellular = Zellular("downtime-monitoring", network)
# -- end: configuring eigenlayer network --

nodes_state: dict[str, str] = {addr: "up" for addr in MONITORED_NODES}

nodes_events: dict[str, list[dict[str, Any]]] = {
    addr: [{"state": "up", "timestamp": 0}] for addr in MONITORED_NODES
}

app = FastAPI()

def check_node_state(node_address: str, node_url: str) -> str:
    try:
        response = requests.get(f"{node_url}/health", timeout=REQUEST_TIMEOUT)
        return "up" if response.status_code == 200 else "down"
    except requests.RequestException:
        return "down"

def monitor_loop():
    while True:
        node_address = random.choice(list(MONITORED_NODES.keys()))
        node_url = MONITORED_NODES[node_address]

        new_state = check_node_state(node_address, node_url)
        last_state = nodes_state.get(node_address)

        # -- start: sending event to zellular --
        if last_state != new_state:
            event = {
                "address": node_address,
                "state": new_state,
                "timestamp": int(time.time())
            }
            zellular.send([event], blocking=False)
            logger.info(f"Sent state change event to Zellular: {node_address} ➔ {new_state}")
        else:
            logger.info(f"No change: {node_address} is {new_state}")
        # -- end: sending event to zellular --

        time.sleep(POLL_INTERVAL_SECONDS)

# -- start: applying event to local state --
def apply_event(event: dict[str, Any]):
    address = event["address"]
    state = event["state"]
    timestamp = event["timestamp"]

    last_state = nodes_state.get(address)
    if last_state != state:
        nodes_state[address] = state
        nodes_events[address].append({
            "state": state,
            "timestamp": timestamp
        })
        logger.info(f"Applied event: {address} ➔ {state}")
    else:
        logger.warning(f"Duplicate state for {address}, event ignored")
# -- end: applying event to local state --

def process_loop():
    for batch, index in zellular.batches():
        events = json.loads(batch)
        for event in events:
                apply_event(event)

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
    if address not in nodes_events:
        raise HTTPException(status_code=404, detail="Address not found")

    events = nodes_events[address]
    total_downtime = calculate_downtime(events, from_timestamp, to_timestamp)
    return JSONResponse({
        "address": address,
        "from_timestamp": from_timestamp,
        "to_timestamp": to_timestamp,
        "total_downtime_seconds": total_downtime
    })

# -- start: running monitor and process loops --
if __name__ == "__main__":
    threading.Thread(target=monitor_loop, daemon=True).start()
    threading.Thread(target=process_loop, daemon=True).start()
    uvicorn.run(app, host="0.0.0.0", port=5000)
# -- end: running monitor and process loops --
