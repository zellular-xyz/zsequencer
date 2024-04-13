import json
import os
import sys
import time
from typing import Any, Dict

import requests

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


def send_tx() -> None:
    op: Dict[str, Any] = {
        "transactions": [
            {
                "name": "foo",
                "app": "foo_app",
                "amount": 1,
                "timestamp": int(time.time()),
                "version": 6,
            },
            {
                "name": "foo",
                "app": "foo_app",
                "amount": 2,
                "timestamp": int(time.time()),
                "version": 6,
            },
        ],
        "timestamp": int(time.time()),
    }
    print(f"send new operations: {op}")
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
            print("\nreceive finalized operations: ", finalized_txs)
            break
        time.sleep(5)


if __name__ == "__main__":
    send_tx()
    sync()
