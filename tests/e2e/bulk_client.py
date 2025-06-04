import json
import time
from uuid import uuid4

import requests

from common.logger import zlogger

BULK_SIZE = 500_000


def main() -> None:
    gateway = "http://localhost:6008/node/batches"
    t = int(time.time())
    txs = [
        json.dumps({"tx_id": str(uuid4()), "operation": "foo", "t": t})
        for i in range(BULK_SIZE)
    ]
    r = requests.put(gateway, json={"simple_app": txs})
    zlogger.info(r.text)


if __name__ == "__main__":
    main()
