"""
Main script to run Zellular Node and Sequencer tasks.
"""

import asyncio
import logging
import os
import sys
import threading
import time

import aiohttp
from flask import Flask

# Add the parent directory to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import secrets
from common.db import zdb, zconfig
from common.logger import zlogger
from node import tasks as node_tasks
from node.routes import node_blueprint
from sequencer import tasks as sequencer_tasks
from sequencer.routes import sequencer_blueprint
from eigensdk.crypto.bls import attestation


def create_app() -> Flask:
    """Create and configure the Flask application."""
    app: Flask = Flask(__name__)
    app.secret_key = secrets.token_hex(32)

    app.register_blueprint(node_blueprint, url_prefix="/node")
    app.register_blueprint(sequencer_blueprint, url_prefix="/sequencer")
    return app


def run_node_tasks() -> None:
    """Periodically run node tasks."""
    while True:
        time.sleep(zconfig.SEND_TXS_INTERVAL)
        if zconfig.NODE["id"] == zconfig.SEQUENCER["id"]:
            continue

        if zdb.pause_node.is_set():
            continue

        node_tasks.send_txs()
        asyncio.run(node_tasks.send_dispute_requests())


def run_sequencer_tasks() -> None:
    """Run sequencer tasks in an asynchronous event loop."""
    loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_sequencer_tasks_async())


async def run_sequencer_tasks_async() -> None:
    """Asynchronously run sequencer tasks."""
    while True:
        await asyncio.sleep(zconfig.SYNC_INTERVAL)
        if zconfig.NODE["id"] != zconfig.SEQUENCER["id"]:
            continue

        if zdb.pause_node.is_set():
            continue

        await sequencer_tasks.sync()


def run_flask_app(app: Flask) -> None:
    """Run the Flask application."""
    # Set the logging level to WARNING to suppress INFO level logs
    logger: logging.Logger = logging.getLogger("werkzeug")
    logger.setLevel(logging.WARNING)
    app.run(
        host="0.0.0.0",
        port=zconfig.PORT,
        debug=False,
        threaded=True,
        use_reloader=False,
    )


async def fetch_nodes_and_apps() -> None:
    while True:
        await asyncio.sleep(zconfig.FETCH_APPS_AND_NODES_INTERVAL)
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(
                    zconfig.FETCH_APPS_AND_NODES_URL+'/apps.json', timeout=5
                    ) as response:
                    response_json = await response.json()
                    zconfig.APPS.update(response_json)
                
                async with session.get(
                    zconfig.FETCH_APPS_AND_NODES_URL+'/nodes.json', timeout=5
                    ) as response:
                    response_json = await response.json()
                    zconfig.NODES.update(response_json)
                    
                    for node in list(zconfig.NODES.values()):
                        public_key_g2: str = node["public_key_g2"]
                        if public_key_g2 == zconfig.bls_public_key:
                            zconfig.NODE.update(node)
                        node["public_key_g2"] = attestation.new_zero_g2_point()
                        node["public_key_g2"].setStr(public_key_g2.encode("utf-8"))

            except asyncio.TimeoutError:
                zlogger.exception("Fetch Request timeout:")
            except Exception:
                zlogger.exception("An unexpected error occurred:")

    

def run_fetch_data_tasks() -> None:
    """Run sequencer tasks in an asynchronous event loop."""
    loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(fetch_nodes_and_apps())

def main() -> None:
    """Main entry point for running the Zellular Node."""
    app: Flask = create_app()

    # Start periodic task in a thread
    sync_thread: threading.Thread = threading.Thread(target=run_sequencer_tasks)
    sync_thread.start()

    node_tasks_thread: threading.Thread = threading.Thread(target=run_node_tasks)
    node_tasks_thread.start()

    fetch_nodes_and_apps_thread: threading.Thread = threading.Thread(target=run_fetch_data_tasks)
    fetch_nodes_and_apps_thread.start()

    # Start the Zellular node Flask application
    run_flask_app(app)


if __name__ == "__main__":
    main()
