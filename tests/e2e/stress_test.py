import argparse
import json
import os
import random
import threading
import time
from queue import Queue
from typing import Any
from uuid import uuid4

from requests.exceptions import RequestException
from zellular import StaticNetwork, Zellular

from common.logger import zlogger
from tests.e2e.run import SIMULATION_DATA_DIR, SimulationConfig, load_simulation_config

NUM_THREADS = 100
TOTAL_REQUESTS = 100_000


def worker(
    config: SimulationConfig,
    job_queue: Queue[int],
    network: StaticNetwork,
    nodes: dict[str, Any],
) -> None:
    while not job_queue.empty():
        try:
            job = job_queue.get_nowait()
        except Exception:
            return

        port = config.base_port + random.randint(1, config.node_num)
        gateway = f"http://localhost:{port}"
        zellular = Zellular(
            app="simple_app", network=network, gateway=gateway, timeout=2
        )
        t = int(time.time())
        txs = [{"tx_id": str(uuid4()), "operation": "foo", "t": t}]

        try:
            zellular.send(json.dumps(txs))
        except RequestException as e:
            zlogger.error(f"Error sending request to {gateway}: {e}")
            job_queue.put(job)

        job_queue.task_done()


def main(config_path: str) -> None:
    config = load_simulation_config(config_path)

    with open(os.path.join(SIMULATION_DATA_DIR, "nodes.json")) as f:
        nodes = json.load(f)

    network = StaticNetwork(
        nodes,
        threshold_percent=config.shared_env_variables["ZSEQUENCER_THRESHOLD_PERCENT"],
    )

    # Fill the job queue
    job_queue: Queue[int] = Queue()
    for _ in range(TOTAL_REQUESTS):
        job_queue.put(1)

    # Start worker threads
    threads = []
    for _ in range(NUM_THREADS):
        t = threading.Thread(target=worker, args=(config, job_queue, network, nodes))
        t.start()
        threads.append(t)

    # Wait for all threads to complete
    for t in threads:
        t.join()

    zlogger.info(
        f"Finished sending {TOTAL_REQUESTS} requests using {NUM_THREADS} threads."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run threaded zellular stress test client"
    )
    parser.add_argument(
        "--config",
        type=str,
        default="tests/e2e/sample_config.json",
        help="Path to the simulation configuration file",
    )
    args = parser.parse_args()
    main(args.config)
