"""
Main script to run Zellular Node and Sequencer tasks.
"""

import asyncio
import logging
import os
import sys
import threading
import time

from flask import Flask, redirect, url_for

# Add the parent directory to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import secrets
from common.db import zdb, zconfig
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
        time.sleep(zconfig.SEND_BATCH_INTERVAL)
        if zconfig.NODE["id"] == zconfig.SEQUENCER["id"]:
            continue

        if zdb.pause_node.is_set():
            continue

        node_tasks.send_batches()
        asyncio.run(node_tasks.send_dispute_requests())


def run_sequencer_tasks() -> None:
    """Run sequencer tasks in an asynchronous event loop."""
    # loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
    # asyncio.set_event_loop(loop)
    # loop.run_until_complete(run_sequencer_tasks_async())

    run_sequencer_tasks_async()


def run_sequencer_tasks_async() -> None:
    """Asynchronously run sequencer tasks."""
    while True:
        # await asyncio.sleep(zconfig.SYNC_INTERVAL)
        time.sleep(zconfig.SYNC_INTERVAL)
        if zconfig.NODE["id"] != zconfig.SEQUENCER["id"]:
            continue

        if zdb.pause_node.is_set():
            continue

        sequencer_tasks.sync()


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


def main() -> None:
    """Main entry point for running the Zellular Node."""
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
