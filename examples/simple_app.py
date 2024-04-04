import os
import sys
import time
from typing import Any, Dict

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from zsequencer.node import tasks as node_tasks


def send_tx() -> None:
    op: Dict[str, Any] = {
        "name": "foo",
        "app": "foo_app",
        "timestamp": int(time.time() * 1000),
        "version": 6,
    }
    print(f"send new operations: {op}")
    node_tasks.init_tx(op)


def sync() -> None:
    last: int = 0
    while True:
        finalized_txs: Dict[str, Any] = node_tasks.get_finalized(last)
        if finalized_txs:
            last: int = max(tx["index"] for tx in finalized_txs.values())
            print("receive finalized operations: ", finalized_txs)
        time.sleep(5)


if __name__ == "__main__":
    send_tx()
    sync()
