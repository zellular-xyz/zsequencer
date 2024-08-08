"""This script simulates a simple app which uses Zsequencer."""

import argparse
import json
import os
import sys
import threading
import time
import math
from typing import Any

import requests
from requests.exceptions import RequestException

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from zsequencer.common.logger import zlogger

BATCH_SIZE: int = 100_000
BATCH_NUMBER: int = 1
CHECK_STATE_INTERVAL: float = 0.05
THREAD_NUMBERS_FOR_SENDING_TXS = 100

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


def check_state(
    app_name: str, node_url: str, batch_number: int, batch_size: int
) -> None:
    """Continuously check the node state until all the batches are finalized."""
    start_time: float = time.time()
    while True:
        try:
            response: requests.Response = requests.get(
                f"{node_url}/node/{app_name}/transactions/finalized/last"
            )
            response.raise_for_status()
            last_finalized_batch: dict[str, Any] = response.json()
            last_finalized_index: int = last_finalized_batch["data"].get("index", 0)
            zlogger.info(
                f"Last finalized index: {last_finalized_index} -  ({time.time() - start_time} s)"
            )
            if last_finalized_index == batch_number:
                break
        except RequestException as error:
            zlogger.error(f"Error checking state: {error}")
        time.sleep(CHECK_STATE_INTERVAL)


def send_batches(app_name: str, batches: list[dict[str, Any]], node_url: str, thread_index: int) -> None:
    """Send multiple batches of transactions to the node."""
    for i, batch in enumerate(batches):
        zlogger.info(f'Thread {thread_index}: sending batch {i + 1} with {len(batch["transactions"])} transactions')
        try:
            string_data: str = json.dumps(batch)
            response: requests.Response = requests.put(
                url=f"{node_url}/node/{app_name}/transactions",
                data=string_data,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
        except RequestException as error:
            zlogger.error(f"Thread {thread_index}: Error sending transactions: {error}")

def send_batches_with_threads(
    app_name: str, transaction_batches: list[dict[str, Any]], node_url: str, num_threads: int = 100
) -> None:
    """Send batches of transactions to the node using multiple threads."""
    num_batches = len(transaction_batches)
    # Adjust number of threads if there are fewer batches than threads
    if num_batches < num_threads:
        num_threads = num_batches

    threads = []
    batches_per_thread = math.ceil(num_batches / num_threads)

    for i in range(num_threads):
        start_index = i * batches_per_thread
        end_index = min(start_index + batches_per_thread, num_batches)
        batch_subset = transaction_batches[start_index:end_index]
        
        if not batch_subset:
            break
        
        thread = threading.Thread(target=send_batches, args=(app_name, batch_subset, node_url, i))
        threads.append(thread)
        thread.start()

    # Wait for all threads to finish
    for t in threads:
        t.join()

    zlogger.info("All batches have been sent.")


def generate_dummy_transactions(
    batch_size: int, batch_number: int
) -> list[dict[str, Any]]:
    """Create batches of transactions."""
    return [
        {
            "transactions": [
                json.dumps(
                    {
                        "operation": "foo",
                        "serial": f"{batch_num}_{tx_num}",
                        "version": 6,
                    }
                )
                for tx_num in range(batch_size)
            ],
        }
        for batch_num in range(batch_number)
    ]


def main() -> None:
    """Run the simple app."""
    args: argparse.Namespace = parse_args()
    transaction_batches: list[dict[str, Any]] = generate_dummy_transactions(
        BATCH_SIZE, BATCH_NUMBER
    )
    sender_thread: threading.Thread = threading.Thread(
        target=send_batches_with_threads, args=[args.app_name, transaction_batches, args.node_url, THREAD_NUMBERS_FOR_SENDING_TXS]
    )
    sync_thread: threading.Thread = threading.Thread(
        target=check_state,
        args=[args.app_name, args.node_url, BATCH_NUMBER, BATCH_SIZE],
    )

    sender_thread.start()
    sync_thread.start()

    sender_thread.join()
    sync_thread.join()


if __name__ == "__main__":
    main()
