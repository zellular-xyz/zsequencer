"""This script simulates a simple app which uses Zsequencer."""

import argparse
import json
import os
import sys
import threading
import time
from typing import Any

import requests
from requests.exceptions import RequestException

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from zsequencer.common.logger import zlogger

BATCH_SIZE: int = 100_000
BATCH_NUMBER: int = 1
CHECK_STATE_INTERVAL: float = 0.05


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


def sending_batches(
    app_name: str, transaction_batches: list[dict[str, Any]], node_url: str
) -> None:
    """Send batches of transactions to the node."""
    for i, batch in enumerate(transaction_batches):
        zlogger.info(f'sending {i + 1} new batches with {len(batch["transactions"])} new operations ')
        params = {
            "app_name": app_name
        }
        try:
            json_data: str = json.dumps(batch)
            response: requests.Response = requests.put(
                url=f"{node_url}/node/transactions",
                data=json_data,
                params=params,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
        except RequestException as error:
            zlogger.error(f"Error sending transactions: {error}")


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
        target=sending_batches, args=[args.app_name, transaction_batches, args.node_url]
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
