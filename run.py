"""Main script to run Zellular Node and Sequencer tasks."""

import asyncio
import logging
import os
import sys
import threading
import time

import requests
from flask import Flask, redirect, url_for

# Add the parent directory to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import secrets

from common.db import zdb
from common.logger import zlogger
from config import zconfig
from node import tasks as node_tasks
from node.routes import node_blueprint
from sequencer import tasks as sequencer_tasks
from sequencer.routes import sequencer_blueprint


def create_app() -> Flask:
    """Create and configure the Flask application."""
    app: Flask = Flask(__name__)
    app.secret_key = secrets.token_hex(32)

    app.register_blueprint(node_blueprint, url_prefix="/node")
    app.register_blueprint(sequencer_blueprint, url_prefix="/sequencer")

    @app.route("/", methods=["GET"])
    def base_redirect():
        return redirect(url_for("node.get_state"))

    return app


def run_node_tasks() -> None:
    """Periodically run node tasks."""
    while True:
        if zconfig.NODE["id"] == zconfig.SEQUENCER["id"] or zdb.pause_node.is_set():
            time.sleep(0.1)
            continue

        node_tasks.send_batches()
        asyncio.run(node_tasks.send_dispute_requests())


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

        if zdb.pause_node.is_set():
            continue

        await sequencer_tasks.sync()


def shutdown_if_not_reachable() -> None:
    """Check node reachability and shutdown if not reachable."""
    time.sleep(5)  # Give Flask time to start

    try:
        node_host = zconfig.HOST.replace("http://", "").replace("https://", "")
        url = zconfig.REMOTE_HOST_CHECKER_BASE_URL.format(
            host=node_host, port=zconfig.PORT
        )
        response = requests.get(url)

        if response.status_code == 200:
            if response.text.lower() == "true":
                # Node is reachable and nothing to do
                return
            else:
                zlogger.error(
                    "Node not reachable at {}:{}. Check firewall or port forwarding. Shutting down...".format(
                        node_host, zconfig.PORT
                    )
                )
        else:
            zlogger.error(
                f"Node reachability check failed with status code: {response.status_code}"
            )

    except Exception as e:
        zlogger.error(f"Failed to check node reachability: {e}")

    os._exit(1)


def main() -> None:
    """Main entry point for running the Zellular Node."""
    app: Flask = create_app()

    # Start periodic tasks in threads
    sequencer_tasks_thread = threading.Thread(target=run_sequencer_tasks, daemon=True)
    sequencer_tasks_thread.start()

    node_tasks_thread = threading.Thread(target=run_node_tasks, daemon=True)
    node_tasks_thread.start()

    # Start reachability check in separate thread
    if zconfig.CHECK_REACHABILITY_OF_NODE_URL:
        reachability_check_thread = threading.Thread(
            target=shutdown_if_not_reachable, daemon=True
        )
        reachability_check_thread.start()

    # Set the logging level to WARNING to suppress INFO level logs
    logger: logging.Logger = logging.getLogger("werkzeug")
    logger.setLevel(logging.WARNING)
    zlogger.info("Starting flask on port %s", zconfig.PORT)

    # Run Flask directly in the main thread - this is a blocking call
    app.run(
        host="0.0.0.0",
        port=zconfig.PORT,
        debug=False,
        threaded=False,
        use_reloader=False,
    )


if __name__ == "__main__":
    main()
