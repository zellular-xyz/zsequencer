import random
import time
import threading
import json
import asyncio
import logging
from typing import Any
import requests
import aiohttp
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from zellular import Zellular
from blspy import PrivateKey, G1Element, G2Element, PopSchemeMPL
import uvicorn

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("downtime-monitor")

# Node URL configuration
MONITORED_NODES = {
    "0xNodeA123": "http://localhost:8001",
    "0xNodeB456": "http://localhost:8002",
    "0xNodeC789": "http://localhost:8003",
}

# Load health checker nodes configuration
with open("monitoring_nodes.json") as f:
    MONITORING_NODES: dict[str, dict[str, str]] = json.load(f)

# Aggregate public key of all health checker nodes (precomputed offline)
AGGREGATE_PUBLIC_KEY_HEX = "your_aggregate_pubkey_hex_here"
AGGREGATE_PUBLIC_KEY = G1Element.from_bytes(bytes.fromhex(AGGREGATE_PUBLIC_KEY_HEX))

# Self node ID (this node's name in the health checker nodes config)
SELF_NODE_ID = "Node1"  # Adjust this value per node

REQUEST_TIMEOUT = 3
POLL_INTERVAL_SECONDS = 10
MAX_TIMESTAMP_DRIFT = 10  # seconds

# Initialize Zellular client
zellular = Zellular("downtime-monitor", "http://37.27.41.237:6001/", threshold_percent=1)

node_health_status: dict[str, str] = {addr: "up" for addr in MONITORED_NODES}

node_health_events: dict[str, list[dict[str, Any]]] = {
    addr: [{"state": "up", "timestamp": 0}] for addr in MONITORED_NODES
}

# BLS private key (Load securely in production)
sk = PrivateKey.from_bytes(bytes.fromhex("your_private_key_hex_here"))
pk = sk.get_g1()

app = FastAPI()

def check_node_health(node_address: str, node_url: str) -> str:
    try:
        response = requests.get(f"{node_url}/health", timeout=REQUEST_TIMEOUT)
        return "up" if response.status_code == 200 else "down"
    except requests.RequestException:
        return "down"

def monitor_loop():
    while True:
        node_address = random.choice(list(MONITORED_NODES.keys()))
        node_url = MONITORED_NODES[node_address]

        new_state = check_node_health(node_address, node_url)
        last_state = node_health_status.get(node_address)

        if last_state != new_state:
            asyncio.run(handle_state_change(node_address, new_state))
        else:
            logger.info(f"No change: {node_address} is {new_state}")

        time.sleep(POLL_INTERVAL_SECONDS)

@app.get("/status")
def check_status(address: str, timestamp: int) -> dict[str, Any]:
    if address not in MONITORED_NODES:
        raise HTTPException(status_code=404, detail="Address not found")

    current_time = int(time.time())
    if abs(current_time - timestamp) > MAX_TIMESTAMP_DRIFT:
        raise HTTPException(status_code=400, detail="Timestamp drift too large")

    url = MONITORED_NODES[address]
    state = check_node_health(address, url)

    message = f"Address: {address}, State: {state}, Timestamp: {timestamp}".encode("utf-8")
    signature = PopSchemeMPL.sign(sk, message)

    return {
        "address": address,
        "state": state,
        "timestamp": timestamp,
        "signature": signature.serialize().hex()
    }

async def fetch_status(session: aiohttp.ClientSession, node_name: str, node_info: dict[str, str], address: str, timestamp: int):
    try:
        async with session.get(f"{node_info['url']}/status", params={"address": address, "timestamp": timestamp}, timeout=REQUEST_TIMEOUT) as response:
            data = await response.json()
            return node_name, data["state"], data["signature"]
    except Exception:
        return node_name, None, None

async def query_monitoring_nodes_for_status(address: str) -> tuple[list[tuple[str, str, str]], int]:
    timestamp = int(time.time())
    async with aiohttp.ClientSession() as session:
        tasks = [
            fetch_status(session, node, info, address, timestamp)
            for node, info in MONITORING_NODES.items()
            if node != SELF_NODE_ID
        ]
        results = await asyncio.gather(*tasks)
    return results, timestamp

def aggregate_signatures(message: bytes, expected_value: Any, results: list[tuple[str, Any, str]]):
    valid_signatures = []
    non_signers = []

    for node_name, value, signature_hex in results:
        if value != expected_value or signature_hex is None:
            non_signers.append(node_name)
            continue

        try:
            pubkey = G1Element.from_bytes(bytes.fromhex(MONITORING_NODES[node_name]["pubkey"]))
            signature = G2Element.from_bytes(bytes.fromhex(signature_hex))
            if PopSchemeMPL.verify(pubkey, message, signature):
                valid_signatures.append(signature)
            else:
                non_signers.append(node_name)
        except Exception:
            non_signers.append(node_name)

    if len(valid_signatures) < (2 * len(MONITORING_NODES)) // 3 + 1:
        raise ValueError("Not enough valid signatures to reach threshold")

    aggregated_signature = PopSchemeMPL.aggregate(valid_signatures)
    return aggregated_signature, non_signers

async def handle_state_change(node_address: str, new_state: str):
    results, timestamp = await query_monitoring_nodes_for_status(node_address)

    # Locally sign our observation and append it
    message = f"Address: {node_address}, State: {new_state}, Timestamp: {timestamp}".encode("utf-8")
    signature = PopSchemeMPL.sign(sk, message)
    results.append((SELF_NODE_ID, new_state, signature.serialize().hex()))

    try:
        aggregated_signature, non_signers = aggregate_signatures(message, new_state, results)

        event = {
            "address": node_address,
            "state": new_state,
            "timestamp": timestamp,
            "aggregated_signature": aggregated_signature.serialize().hex(),
            "non_signing_nodes": non_signers
        }
        zellular.send([event], blocking=False)
        logger.info(f"✅ Sent event with proof: {node_address} ➔ {new_state}")
    except ValueError as e:
        logger.error(f"❌ Could not aggregate proof: {str(e)}")

def verify_event(event: dict[str, Any]) -> bool:
    address = event["address"]
    state = event["state"]
    timestamp = event["timestamp"]
    signature_hex = event["aggregated_signature"]
    non_signing_nodes = event.get("non_signing_nodes", [])

    message = f"Address: {address}, State: {state}, Timestamp: {timestamp}".encode("utf-8")
    signature = G2Element.from_bytes(bytes.fromhex(signature_hex))

    aggregate_pubkey = AGGREGATE_PUBLIC_KEY

    for node_id in non_signing_nodes:
        node_pubkey = G1Element.from_bytes(bytes.fromhex(MONITORING_NODES[node_id]["pubkey"]))
        aggregate_pubkey += node_pubkey.negate()

    return PopSchemeMPL.verify(aggregate_pubkey, message, signature)

def apply_event(event: dict[str, Any]):
    address = event["address"]
    state = event["state"]
    timestamp = event["timestamp"]

    last_state = node_health_status.get(address)
    if last_state != state:
        node_health_status[address] = state
        node_health_events[address].append({
            "state": state,
            "timestamp": timestamp
        })
        logger.info(f"Applied event: {address} ➔ {state}")
    else:
        logger.warning(f"Duplicate state for {address}, event ignored")

def process_loop():
    for batch, index in zellular.batches():
        events = json.loads(batch)
        for event in events:
            if verify_event(event):
                apply_event(event)
            else:
                logger.error(f"Invalid proof for event {event['address']}, ignored")

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
    if address not in node_health_events:
        raise HTTPException(status_code=404, detail="Address not found")

    events = node_health_events[address]
    total_downtime = calculate_downtime(events, from_timestamp, to_timestamp)

    message = f"Address: {address}, Downtime: {total_downtime}, From: {from_timestamp}, To: {to_timestamp}".encode("utf-8")
    signature = PopSchemeMPL.sign(sk, message)

    return JSONResponse({
        "address": address,
        "from_timestamp": from_timestamp,
        "to_timestamp": to_timestamp,
        "total_downtime_seconds": total_downtime,
        "signature": signature.serialize().hex()
    })

async def fetch_downtime(session: aiohttp.ClientSession, node_name: str, node_info: dict[str, str], address: str, from_timestamp: int, to_timestamp: int):
    try:
        async with session.get(f"{node_info['url']}/downtime", params={"address": address, "from_timestamp": from_timestamp, "to_timestamp": to_timestamp}, timeout=REQUEST_TIMEOUT) as response:
            data = await response.json()
            return node_name, data["total_downtime_seconds"], data["signature"]
    except Exception:
        return node_name, None, None

async def query_monitoring_nodes_for_downtime(address: str, from_timestamp: int, to_timestamp: int) -> tuple[list[tuple[str, int, str]], int]:
    async with aiohttp.ClientSession() as session:
        tasks = [
            fetch_downtime(session, node, info, address, from_timestamp, to_timestamp)
            for node, info in MONITORING_NODES.items()
            if node != SELF_NODE_ID
        ]
        results = await asyncio.gather(*tasks)

    events = node_health_events.get(address)
    if not events:
        raise HTTPException(status_code=404, detail="Address not found")

    total_downtime = calculate_downtime(events, from_timestamp, to_timestamp)

    message = f"Address: {address}, Downtime: {total_downtime}, From: {from_timestamp}, To: {to_timestamp}".encode("utf-8")
    signature = PopSchemeMPL.sign(sk, message)
    results.append((SELF_NODE_ID, total_downtime, signature.serialize().hex()))

    return results, total_downtime

@app.get("/aggregate_downtime")
async def aggregate_downtime(address: str, from_timestamp: int, to_timestamp: int):
    results, target_downtime = await query_monitoring_nodes_for_downtime(address, from_timestamp, to_timestamp)

    message = f"Address: {address}, Downtime: {target_downtime}, From: {from_timestamp}, To: {to_timestamp}".encode("utf-8")
    aggregated_signature, non_signers = aggregate_signatures(message, target_downtime, results)

    return {
        "address": address,
        "from_timestamp": from_timestamp,
        "to_timestamp": to_timestamp,
        "total_downtime_seconds": target_downtime,
        "aggregated_signature": aggregated_signature.serialize().hex(),
        "non_signing_nodes": non_signers
    }

if __name__ == "__main__":
    threading.Thread(target=monitor_loop, daemon=True).start()
    threading.Thread(target=process_loop, daemon=True).start()
    uvicorn.run(app, host="0.0.0.0", port=5000)
