"""This script simulates a simple app which uses Zsequencer."""

import argparse
import json
import os
import sys
import threading
import time
import math
import random

from typing import Any, List, Dict

import requests
from requests.exceptions import RequestException

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from zsequencer.common.logger import zlogger

# BATCH_SIZE: int = 500
BATCH_NUMBER = 200
NUM_THREADS = 20
CHECK_STATE_INTERVAL: float = 0.05


# THREAD_NUMBERS_FOR_SENDING_TXS = 50


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Simulate a simple app using Zsequencer."
    )
    parser.add_argument(
        "--app_name", type=str, default="simple_app", help="Name of the application."
    )
    parser.add_argument(
        "--node_url", type=str, default="http://localhost:6003", help="URL of the node."
    )
    return parser.parse_args()


def check_state(app_name: str,
                node_url: str,
                batch_number: int):
    """Continuously check the node state until all the batches are finalized."""
    start_time: float = time.time()
    while True:
        try:
            response: requests.Response = requests.get(
                f"{node_url}/node/{app_name}/batches/finalized/last"
            )
            response.raise_for_status()
            last_finalized_batch: dict[str, Any] = response.json()["data"]
            last_finalized_index: int = last_finalized_batch.get("index", 0)
            zlogger.info(
                f"Last finalized index: {last_finalized_index} -  ({time.time() - start_time} s)"
            )
            if last_finalized_index == batch_number:
                break
        except RequestException as error:
            zlogger.error(f"Error checking state: {error}")
        time.sleep(CHECK_STATE_INTERVAL)


def send_batches(app_name: str, batches: list[dict[str, Any]], node_url: str, thread_index: int):
    """Send multiple batches of transactions to the node."""
    for i, batch in enumerate(batches):
        zlogger.info(f'Thread {thread_index}: sending batch {i + 1} with {len(batch)} transactions')
        try:
            string_data: str = json.dumps(batch)
            response: requests.Response = requests.put(
                url=f"{node_url}/node/{app_name}/batches",
                data=string_data,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
        except RequestException as error:
            zlogger.error(f"Thread {thread_index}: Error sending batch of transactions: {error}")


def batch_generator(items, num_threads):
    batch_size = math.ceil(len(items) / num_threads)
    batch_idx = 0
    while True:
        batch = items[batch_idx * batch_size: (batch_idx + 1) * batch_size]
        if len(batch) == 0:
            return
        yield batch_idx, batch
        batch_idx += 1


def send_batches_with_threads(app_name: str,
                              batches,
                              node_url: str,
                              num_threads: int = NUM_THREADS):
    """Send batches of transactions to the node using multiple threads."""
    batch_gen = batch_generator(items=batches,
                                num_threads=num_threads)
    threads = [
        threading.Thread(target=send_batches, args=(app_name, batch, node_url, batch_idx))
        for batch_idx, batch in batch_gen
    ]

    for thread in threads:
        thread.start()
        thread.join()

    zlogger.info("All batches have been sent.")


def generate_dummy_transactions(batch_number: int) -> List[List[Dict]]:
    """Create batches of transactions with random batch sizes."""
    return [
        [
            {
                "operation": "foo",
                "serial": f"{batch_num}_{tx_num}",
                "version": 6,
            } for tx_num in range(random.randint(100, 500))
        ] for batch_num in range(batch_number)
    ]


def main() -> None:
    """Run the simple app."""
    args: argparse.Namespace = parse_args()
    batches = generate_dummy_transactions(BATCH_NUMBER)

    sender_thread = threading.Thread(
        target=send_batches_with_threads,
        args=[args.app_name, batches, args.node_url, NUM_THREADS]
    )
    # sync_thread = threading.Thread(
    #     target=check_state,
    #     args=[args.app_name, args.node_url, BATCH_NUMBER],
    # )
    #
    sender_thread.start()
    # sync_thread.start()
    #
    sender_thread.join()
    # sync_thread.join()


if __name__ == "__main__":
    main()
