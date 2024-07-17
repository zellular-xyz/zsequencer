"""This script simulates a simple app which uses Zsequencer."""

import json
import os
import sys
import threading
import time
from typing import Any

import requests

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
BATCH_SIZE: int = 100_000
BATCH_NUMBER: int = 1
APP_NAME: str = "simple_app"
NODE_URL: str = "http://localhost:6003"


def check_state() -> None:
    """Continuously check and print the node state until all the transactions are finalized."""
    start_time: float = time.time()
    while True:
        last_finalized_tx: dict[str, Any] = requests.get(
            f"{NODE_URL}/node/{APP_NAME}/transactions/finalized/last"
        ).json()
        print(
            f'Last finalized index: {last_finalized_tx["data"].get("index", 0)} -  ({time.time() - start_time} s)'
        )
        if last_finalized_tx["data"].get("index") == BATCH_NUMBER * BATCH_SIZE:
            break
        time.sleep(0.1)


def sending_transactions(transaction_batches: list[dict[str, Any]]) -> None:
    """Send batches of transactions to the node."""
    for i, batch in enumerate(transaction_batches):
        print(f'sending {len(batch["transactions"])} new operations (batch {i})')
        requests.put(
            url=f"{NODE_URL}/node/transactions",
            data=json.dumps(batch),
            headers={"Content-Type": "application/json"},
        )


def generate_dummy_transactions() -> list[dict[str, Any]]:
    """Create batches of transactions."""
    timestamp: int = int(time.time())
    return [
        {
            "app_name": APP_NAME,
            "transactions": [
                json.dumps(
                    {
                        "operation": "foo",
                        "serial": f"{batch_num}_{tx_num}",
                        "version": 6,
                    }
                )
                for tx_num in range(BATCH_SIZE)
            ],
            "timestamp": timestamp,
        }
        for batch_num in range(BATCH_NUMBER)
    ]


def main() -> None:
    """run the simple app."""
    transaction_batches: list[dict[str, Any]] = generate_dummy_transactions()
    sender_thread = threading.Thread(
        target=sending_transactions, args=[transaction_batches]
    )
    sync_thread = threading.Thread(target=check_state)

    sender_thread.start()
    sender_thread.join()

    sync_thread.start()
    sync_thread.join()


if __name__ == "__main__":
    main()
