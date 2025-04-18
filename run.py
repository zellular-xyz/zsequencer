"""Main script to run Zellular Node and Sequencer tasks."""

import asyncio
import logging
import os
import sys
import threading
import time
import requests
from flask import Flask, redirect, url_for
from urllib.parse import urljoin

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
    zlogger.info("Starting flask on port %s", zconfig.PORT)
    app.run(
        host="0.0.0.0",
        port=zconfig.PORT,
        debug=False,
        threaded=False,
        use_reloader=False,
    )


def check_node_reachability() -> bool:
    """Check if node is reachable."""
    if not zconfig.CHECK_REACHABILITY_OF_NODE_URL:
        return True
        
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


def main() -> None:
    """Main entry point for running the Zellular Node."""
    if not check_node_reachability():
        zlogger.error("Node is not reachable. Exiting...")
        sys.exit(1)

    app: Flask = create_app()

    # Start periodic task in a thread
    sync_thread: threading.Thread = threading.Thread(target=run_sequencer_tasks)
    sync_thread.start()

    node_tasks_thread: threading.Thread = threading.Thread(target=run_node_tasks)
    node_tasks_thread.start()

    # Start the Zellular node Flask application
    run_flask_app(app)


if __name__ == "__main__":
    main()
