import json
import os
import sys
import time
from typing import Any, Dict
import threading

import requests

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


def send_batch_txs(batch_number) -> None:
    op: Dict[str, Any] = {
        "transactions": [
            {
                "name": "foo",
                "app": "foo_app",
                "serial": f"{batch_number}_{i}",
                "timestamp": int(time.time()),
                "version": 6,
            }
            for i in range(500)
        ],
        "timestamp": int(time.time()),
    }
    print(
        f'sending {len(op["transactions"])} new operations (batch {batch_number + 1})'
    )
    response = requests.put(
        "http://localhost:6003/node/transactions",
        json.dumps(op),
        headers={"Content-Type": "application/json"},
    )
    print(response.json())


def sync() -> None:
    last: int = 0
    while True:
        response = requests.get(
            "http://localhost:6003/node/transactions",
            params={"after": last, "states": ["finalized"]},
        )
        finalized_txs = response.json().get("data")
        if finalized_txs:
            last: int = max(tx["index"] for tx in finalized_txs)
            print("\nreceive finalized indexes: ", [t["index"] for t in finalized_txs])
        time.sleep(5)


def start_sending_transactions():
    for batch_number in range(10):
        send_batch_txs(batch_number)
        time.sleep(2)


if __name__ == "__main__":
    sender_thread = threading.Thread(target=start_sending_transactions)
    sync_thread = threading.Thread(target=sync)

    sender_thread.start()
    sync_thread.start()

    sync_thread.join()
    sender_thread.join()
