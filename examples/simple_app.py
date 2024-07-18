"""This script simulates a simple app which uses Zsequencer."""

import argparse
import json
import os
import sys
import threading
import time
from typing import Any

import requests

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Simulate a simple app using Zsequencer."
    )
    parser.add_argument(
        "--batch_size",
        type=int,
        default=100_000,
        help="Size of each transaction batch.",
    )
    parser.add_argument(
        "--batch_number", type=int, default=1, help="Number of transaction batches."
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
    """Continuously check and print the node state until all the transactions are finalized."""
    start_time: float = time.time()
    while True:
        last_finalized_tx: dict[str, Any] = requests.get(
            f"{node_url}/node/{app_name}/transactions/finalized/last"
        ).json()
        print(
            f'Last finalized index: {last_finalized_tx["data"].get("index", 0)} -  ({time.time() - start_time} s)'
        )
        if last_finalized_tx["data"].get("index") == batch_number * batch_size:
            break
        time.sleep(0.1)


def sending_transactions(
    transaction_batches: list[dict[str, Any]], node_url: str
) -> None:
    """Send batches of transactions to the node."""
    for i, batch in enumerate(transaction_batches):
        print(f'sending {len(batch["transactions"])} new operations (batch {i})')
        requests.put(
            url=f"{node_url}/node/transactions",
            data=json.dumps(batch),
            headers={"Content-Type": "application/json"},
        )


def generate_dummy_transactions(
    app_name: str, batch_size: int, batch_number: int
) -> list[dict[str, Any]]:
    """Create batches of transactions."""
    timestamp: int = int(time.time())
    return [
        {
            "app_name": app_name,
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
            "timestamp": timestamp,
        }
        for batch_num in range(batch_number)
    ]


def main() -> None:
    """run the simple app."""
    args = parse_args()
    transaction_batches: list[dict[str, Any]] = generate_dummy_transactions(
        args.app_name, args.batch_size, args.batch_number
    )
    sender_thread = threading.Thread(
        target=sending_transactions, args=[transaction_batches, args.node_url]
    )
    sync_thread = threading.Thread(
        target=check_state,
        args=[args.app_name, args.node_url, args.batch_number, args.batch_size],
    )

    sender_thread.start()
    sender_thread.join()

    sync_thread.start()
    sync_thread.join()


if __name__ == "__main__":
    main()
