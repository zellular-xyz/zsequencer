"""Main script to run Zellular Node and Sequencer tasks."""

import asyncio
import logging
import os
import sys
import threading
import time
from urllib.parse import urljoin

import requests
from flask import Flask, redirect, url_for

# Add the parent directory to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import secrets
# Add to imports at the top
from threading import Event
from common.db import zdb
from common.logger import zlogger
from config import zconfig
from node import tasks as node_tasks
from node.routes import node_blueprint
from sequencer import tasks as sequencer_tasks
from sequencer.routes import sequencer_blueprint

# Add shutdown event as a global variable
shutdown_event = Event()


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
    while not shutdown_event.is_set():
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
    while not shutdown_event.is_set():
        await asyncio.sleep(zconfig.SYNC_INTERVAL)
        if zconfig.NODE["id"] != zconfig.SEQUENCER["id"]:
            continue

        if zdb.pause_node.is_set():
            continue

        await sequencer_tasks.sync()


def run_flask_app(app: Flask) -> None:
    """Run the Flask application."""
    logger: logging.Logger = logging.getLogger("werkzeug")
    logger.setLevel(logging.WARNING)
    zlogger.info("Starting flask on port %s", zconfig.PORT)

    def flask_thread():
        app.run(
            host="0.0.0.0",
            port=zconfig.PORT,
            debug=False,
            threaded=False,
            use_reloader=False,
        )

    flask_thread = threading.Thread(target=flask_thread)
    flask_thread.daemon = True
    flask_thread.start()


def check_reachability_and_shutdown() -> None:
    """Check node reachability and shutdown if not reachable."""
    time.sleep(2)  # Give Flask time to start
    if zconfig.CHECK_REACHABILITY_OF_NODE_URL and not check_node_reachability():
        zlogger.error("Node is not reachable. Shutting down...")
        shutdown_event.set()
        sys.exit(1)


def main() -> None:
    """Main entry point for running the Zellular Node."""
    app: Flask = create_app()

    # Start periodic tasks in threads
    sync_thread = threading.Thread(target=run_sequencer_tasks, daemon=True)
    sync_thread.start()

    node_tasks_thread = threading.Thread(target=run_node_tasks, daemon=True)
    node_tasks_thread.start()

    # Start reachability check in separate thread
    reachability_thread = threading.Thread(target=check_reachability_and_shutdown, daemon=True)
    reachability_thread.start()

    # Start the Flask application (now non-blocking)
    run_flask_app(app)

    # Wait for shutdown event
    try:
        while not shutdown_event.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown_event.set()
        sys.exit(0)


def check_node_reachability() -> bool:
    """Check if node is reachable."""
    try:
        node_host = zconfig.HOST.replace('http://', '').replace('https://', '')
        response = requests.get(urljoin(zconfig.REMOTE_HOST_CHECKER_BASE_URL, node_host, zconfig.PORT))

        if response.status_code == 200:
            return response.text.lower() == 'true'

        zlogger.error(f"Node reachability check failed with status code: {response.status_code}")
        return False

    except requests.RequestException as e:
        zlogger.error(f"Failed to check node reachability: {e}")
        return False
    except Exception as e:
        zlogger.error(f"Unexpected error during node reachability check: {e}")
        return False


if __name__ == "__main__":
    main()
