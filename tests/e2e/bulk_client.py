import json
import time
from uuid import uuid4

import requests

from common.logger import zlogger

BULK_SIZE = 500_000


def main() -> None:
    gateway = "http://localhost:6008"
    first = requests.get(gateway + "/node/simple_app/batches/finalized/last").json()
    first_index = first["data"]["index"] if first["data"] else 0
    txs = [
        json.dumps({"tx_id": str(uuid4()), "operation": "foo"})
        for i in range(BULK_SIZE)
    ]
    start = time.time()
    r = requests.put(gateway + "/node/batches", json={"simple_app": txs})
    zlogger.info(f"transactions sent: {r.text}")
    while True:
        time.sleep(0.01)
        last = requests.get(gateway + "/node/simple_app/batches/finalized/last").json()
        duration = time.time() - start
        zlogger.info(f"duration: {duration:.2f}, last: {last}")
        if last["data"] and last["data"]["index"] - first_index >= BULK_SIZE:

            zlogger.info(f"Duration: {duration}, Transactions: {BULK_SIZE}, TPS: {int(BULK_SIZE / duration)}")
            break


if __name__ == "__main__":
    main()
