import json
import os
import sys
import threading
import time
from typing import Any, Dict

import requests

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
BATCH_SIZE = 100000
BATCH_NUMBER = 1


def send_batch_txs(batch_num) -> None:
    op: Dict[str, Any] = {
        "transactions": [
            json.dumps(
                {
                    "name": "foo",
                    "app": "foo_app",
                    "serial": f"{batch_num}_{tx_num}",
                    "timestamp": int(time.time()),
                    "version": 6,
                }
            )
            for tx_num in range(BATCH_SIZE)
        ],
        "timestamp": int(time.time()),
    }
    print(f'sending {len(op["transactions"])} new operations (batch {batch_num})')
    requests.put(
        "http://localhost:6003/node/transactions",
        json.dumps(op),
        headers={"Content-Type": "application/json"},
    )


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
            sorted_numbers = sorted([t["index"] for t in finalized_txs])
            print(
                f"\nreceive finalized indexes: [{sorted_numbers[0]}, ..., {sorted_numbers[-1]}]",
            )
        time.sleep(1)


def start_sending_transactions():
    for i in range(BATCH_NUMBER):
        send_batch_txs(i + 1)


if __name__ == "__main__":
    sender_thread = threading.Thread(target=start_sending_transactions)
    sync_thread = threading.Thread(target=sync)

    sender_thread.start()
    sync_thread.start()

    sync_thread.join()
    sender_thread.join()
