import argparse
import json
import os
import random
import threading
import time
from queue import Queue
from uuid import uuid4
from typing import Any

from zellular import StaticNetwork, Zellular
from common.errors import IsSequencerError
from common.logger import zlogger
from tests.e2e.run import SIMULATION_DATA_DIR, load_simulation_config, SimulationConfig


NUM_THREADS = 100
TOTAL_REQUESTS = 10_000
JOB_QUEUE = Queue()
SEQUENCER_PORT_LOCK = threading.Lock()
SEQUENCER_PORT = None


def is_sequencer_error(e: Exception) -> bool:
    try:
        return e.response.json()["error"]["code"] == IsSequencerError.__name__
    except Exception:
        return False


def worker(config: SimulationConfig, network: StaticNetwork, nodes: dict[str, Any]):
    global SEQUENCER_PORT

    while not JOB_QUEUE.empty():
        try:
            JOB_QUEUE.get_nowait()
        except Exception:
            return

        while True:
            port = config.base_port + random.randint(1, config.node_num)
            with SEQUENCER_PORT_LOCK:
                if port == SEQUENCER_PORT:
                    continue

            gateway = f"http://localhost:{port}"
            zellular = Zellular(app="simple_app", network=network, gateway=gateway, timeout=2)
            t = int(time.time())
            txs = [{"tx_id": str(uuid4()), "operation": "foo", "t": t}]

            try:
                zellular.send(json.dumps(txs))
                break  # job succeeded
            except Exception as e:
                if is_sequencer_error(e):
                    with SEQUENCER_PORT_LOCK:
                        SEQUENCER_PORT = port
                    zlogger.warning(f"Port {port} is a sequencer. Skipping it.")
                else:
                    zlogger.error(f"Error on port {port}: {e}")
                    break  # treat other errors as final

        JOB_QUEUE.task_done()


def main(config_path: str) -> None:
    config = load_simulation_config(config_path)

    with open(os.path.join(SIMULATION_DATA_DIR, "nodes.json")) as f:
        nodes = json.load(f)

    network = StaticNetwork(
        nodes,
        threshold_percent=config.shared_env_variables["ZSEQUENCER_THRESHOLD_PERCENT"],
    )

    # Fill the job queue
    for _ in range(TOTAL_REQUESTS):
        JOB_QUEUE.put(1)

    # Start worker threads
    threads = []
    for _ in range(NUM_THREADS):
        t = threading.Thread(target=worker, args=(config, network, nodes))
        t.start()
        threads.append(t)

    # Wait for all threads to complete
    for t in threads:
        t.join()

    zlogger.info(f"Finished sending {TOTAL_REQUESTS} requests using {NUM_THREADS} threads.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run threaded zellular stress test client")
    parser.add_argument(
        "--config",
        type=str,
        default="tests/e2e/sample_config.json",
        help="Path to the simulation configuration file",
    )
    args = parser.parse_args()
    main(args.config)
