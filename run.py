"""Main script to run Zellular Node and Sequencer tasks."""

import asyncio
import logging
import signal
import sys

import requests
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse

from common import errors
from common.db import zdb
from common.logger import zlogger
from common.sequencer_manager import zsequencer_manager
from config import zconfig
from node import tasks as node_tasks
from node.routers import router as node_router
from node.switch import send_dispute_requests
from sabotage.sabotage_simulator import SabotageSimulator
from sequencer import tasks as sequencer_tasks
from sequencer.routers import router as sequencer_router

zlogger.setLevel(logging.getLevelName(zconfig.LOG_LEVEL))


app = FastAPI(title="ZSequencer")

app.include_router(node_router, prefix="/node")
app.include_router(sequencer_router, prefix="/sequencer")

shutdown_event = asyncio.Event()


@app.exception_handler(errors.BaseHTTPError)
async def base_http_exception_handler(
    request: Request, e: errors.BaseHTTPError
) -> JSONResponse:
    client_ip = request.client.host if request.client else "unknown"

    zlogger.log(
        e.log_level,
        f"[API_ERROR] {e.__class__.__name__} at {request.url.path} from {client_ip}: {e.status_code} - {e.detail['error']['message']}",
    )
    return JSONResponse(status_code=e.status_code, content=e.detail)


@app.get("/", include_in_schema=False)
def base_redirect() -> RedirectResponse:
    return RedirectResponse(url="/node/state")


async def run_node_tasks() -> None:
    """Run node tasks in a loop."""
    while not shutdown_event.is_set():
        await asyncio.sleep(0.1)
        if zconfig.NODE["id"] == zconfig.SEQUENCER["id"] or zconfig.is_paused:
            continue
        if not zdb.is_node_reachable:
            break

        await node_tasks.send_batches()
        await send_dispute_requests()


async def run_sequencer_tasks() -> None:
    """Run sequencer tasks in a loop."""
    while not shutdown_event.is_set():
        await asyncio.sleep(zconfig.SYNC_INTERVAL)
        if zconfig.NODE["id"] != zconfig.SEQUENCER["id"]:
            continue

        if zconfig.is_paused:
            continue

        await sequencer_tasks.sync()
        await zsequencer_manager.detect_and_reset_sequencer_on_failover()


async def fetch_apps_and_network_state_periodically() -> None:
    """Periodically fetches apps and nodes data."""
    while not shutdown_event.is_set():
        try:
            await zdb.fetch_apps()
        except Exception:
            zlogger.error("An unexpected error occurred while fetching apps data.")

        try:
            zconfig.fetch_network_state()
        except Exception:
            zlogger.error(
                "An unexpected error occurred while fetching network state.",
            )

        await asyncio.sleep(zconfig.FETCH_APPS_AND_NODES_INTERVAL)


async def check_node_reachability() -> None:
    """Check node reachability"""
    await asyncio.sleep(15)  # Give the server time to start

    try:
        host, port = (
            zconfig.REGISTER_SOCKET.replace("http://", "")
            .replace("https://", "")
            .split(":")
        )
        url = zconfig.REMOTE_HOST_CHECKER_BASE_URL.format(host=host, port=port)
        response = requests.get(url)

        if response.status_code == 200:
            if response.text.lower() == "false":
                zdb.is_node_reachable = False
                zlogger.error(
                    "Node not reachable at {}:{}. Check firewall or port forwarding.".format(
                        host, port
                    )
                )
        else:
            zlogger.error(
                f"Node reachability check failed with status code: {response.status_code}"
            )

    except Exception as e:
        zlogger.error(f"Failed to check node reachability: {e}")


async def run_server() -> None:
    config = uvicorn.Config(
        "run:app", host="0.0.0.0", port=zconfig.PORT, reload=False, log_level="warning"
    )
    global server
    server = uvicorn.Server(config)
    await server.serve()


def shutdown(sig, frame):
    if shutdown_event.is_set():
        return

    zlogger.error(f"Received exit signal {sig} ...")
    shutdown_event.set()
    if "server" in globals():
        server.should_exit = True
    zdb.shutdown()


async def main() -> None:
    """Main entry point for running the Zellular Node."""
    if zconfig.SABOTAGE_SIMULATION:
        sabotage_simulator = SabotageSimulator()
        sabotage_simulator.start_simulating()

    await zsequencer_manager.init_sequencer()
    await zdb.initialize()
    tasks = [
        run_sequencer_tasks(),
        run_node_tasks(),
        fetch_apps_and_network_state_periodically(),
        run_server(),
    ]
    if zconfig.CHECK_REACHABILITY_OF_NODE_URL:
        tasks.append(check_node_reachability())
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        zlogger.error("Keyboard interrupt detected. Exiting...")
        sys.exit(0)
