import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import asyncio
import threading
import time

from flask import Flask

import config
from shared_state import state
from zsequencer.node import tasks as node_tasks
from zsequencer.node.routes import node_blueprint
from zsequencer.sequencer import tasks as sequencer_tasks
from zsequencer.sequencer.routes import sequencer_blueprint


def create_app() -> Flask:
    app: Flask = Flask(__name__)
    app.secret_key = config.SECRET_KEY

    app.register_blueprint(node_blueprint, url_prefix="/node")
    app.register_blueprint(sequencer_blueprint, url_prefix="/sequencer")
    return app


def run_node_tasks() -> None:
    while True:
        time.sleep(config.SEND_TXS_INTERVAL)
        if config.NODE["id"] == config.SEQUENCER["id"]:
            continue

        if state._pause_node.is_set():
            continue

        node_tasks.send_txs()
        node_tasks.send_dispute_requests()


def run_sequencer_tasks() -> None:
    loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_sequencer_tasks_async())


async def run_sequencer_tasks_async() -> None:
    while True:
        time.sleep(config.SYNC_INTERVAL)
        if config.NODE["id"] != config.SEQUENCER["id"]:
            continue

        if state._pause_node.is_set():
            continue

        await sequencer_tasks.sync()


def run_flask_app(app: Flask, port: int) -> None:
    app.run(host="localhost", port=port, debug=True, threaded=True, use_reloader=False)


def main() -> None:
    app: Flask = create_app()

    # Start periodic task in a thread
    sync_thread: threading.Thread = threading.Thread(target=run_sequencer_tasks)
    sync_thread.start()

    node_tasks_thread: threading.Thread = threading.Thread(target=run_node_tasks)
    node_tasks_thread.start()

    # Start the Zellular node Flask application
    run_flask_app(app, 6000)


if __name__ == "__main__":
    main()
