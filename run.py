import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import argparse
import asyncio
import threading
import time

from flask import Flask

from config import zconfig
from shared_state import state
from zsequencer.common.db import zdb
from zsequencer.node import tasks as node_tasks
from zsequencer.node.routes import local_blueprint, node_blueprint
from zsequencer.sequencer import tasks as sequencer_tasks
from zsequencer.sequencer import tss
from zsequencer.sequencer.routes import sequencer_blueprint


def create_app(tss_blueprint) -> Flask:
    app: Flask = Flask(__name__)
    app.secret_key = zconfig.SECRET_KEY

    app.register_blueprint(local_blueprint, url_prefix="/local")
    app.register_blueprint(node_blueprint, url_prefix="/node")
    app.register_blueprint(sequencer_blueprint, url_prefix="/sequencer")
    app.register_blueprint(tss_blueprint, url_prefix="/pyfrost")
    return app


def run_node_tasks() -> None:
    while True:
        time.sleep(zconfig.SEND_TXS_INTERVAL)
        if zconfig.NODE["id"] == zconfig.SEQUENCER["id"]:
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
        time.sleep(zconfig.SYNC_INTERVAL)
        if zconfig.NODE["id"] != zconfig.SEQUENCER["id"]:
            continue

        if state._pause_node.is_set():
            continue

        await sequencer_tasks.sync()


def run_flask_app(app: Flask) -> None:
    app.run(
        host="localhost",
        port=zconfig.PORT,
        debug=True,
        threaded=True,
        use_reloader=False,
    )


def main(node_id) -> None:
    tss_node = tss.gen_node(node_id)
    app: Flask = create_app(tss_node.blueprint)

    # Start periodic task in a thread
    sync_thread: threading.Thread = threading.Thread(target=run_sequencer_tasks)
    sync_thread.start()

    node_tasks_thread: threading.Thread = threading.Thread(target=run_node_tasks)
    node_tasks_thread.start()

    # Start the Zellular node Flask application
    run_flask_app(app)


if __name__ == "__main__":
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Run Zellular Node"
    )
    parser.add_argument(
        "node_id", choices=list(zconfig.NODES.keys()), help="The frost node id"
    )
    args: argparse.Namespace = parser.parse_args()

    main(args.node_id)
