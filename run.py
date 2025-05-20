"""Main script to run Zellular Node and Sequencer tasks."""

import asyncio
import logging
import os
import sys
import threading
import time

import requests
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse

# Add the parent directory to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from common.db import zdb
from common.errors import BaseHTTPError
from common.logger import zlogger
from config import zconfig
from node import tasks as node_tasks
from node.routers import router as node_router
from node.switch import send_dispute_requests
from sequencer import tasks as sequencer_tasks
from sequencer.routers import router as sequencer_router

app = FastAPI()

app.include_router(node_router, prefix="/node")
app.include_router(sequencer_router, prefix="/sequencer")


@app.exception_handler(BaseHTTPError)
async def base_http_exception_handler(
    request: Request, exc: BaseHTTPError
) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=exc.detail)


@app.get("/", include_in_schema=False)
def base_redirect() -> RedirectResponse:
    return RedirectResponse(url="/node/state")


def run_node_tasks() -> None:
    """Run node tasks in a loop."""
    while True:
        time.sleep(1)
        if zconfig.NODE["id"] == zconfig.SEQUENCER["id"] or zconfig.is_paused:
            time.sleep(0.1)
            continue
        if not zdb.is_node_reachable:
            break

        node_tasks.send_batches()
        asyncio.run(send_dispute_requests())


def run_sequencer_tasks() -> None:
    """Run sequencer tasks in an asynchronous event loop."""
    loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(run_sequencer_tasks_async())
    finally:
        loop.close()


async def run_sequencer_tasks_async() -> None:
    """Asynchronously run sequencer tasks."""
    while True:
        await asyncio.sleep(zconfig.SYNC_INTERVAL)
        if zconfig.NODE["id"] != zconfig.SEQUENCER["id"]:
            continue

        if zconfig.is_paused:
            continue

        await sequencer_tasks.sync()


def check_node_reachability() -> None:
    """Check node reachability"""
    time.sleep(5)  # Give the server time to start

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


def main() -> None:
    """Main entry point for running the Zellular Node."""

    # Start periodic tasks in threads
    sequencer_tasks_thread = threading.Thread(target=run_sequencer_tasks)
    sequencer_tasks_thread.start()

    node_tasks_thread = threading.Thread(target=run_node_tasks)
    node_tasks_thread.start()

    # Start reachability check in separate thread
    if zconfig.CHECK_REACHABILITY_OF_NODE_URL:
        reachability_check_thread = threading.Thread(target=check_node_reachability)
        reachability_check_thread.start()

    # Set the logging level to WARNING to suppress INFO level logs
    logger: logging.Logger = logging.getLogger("werkzeug")
    logger.setLevel(logging.WARNING)
    zlogger.info("Starting service on port %s", zconfig.PORT)

    uvicorn.run(
        "run:app",
        host="0.0.0.0",
        port=zconfig.PORT,
        reload=False,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
