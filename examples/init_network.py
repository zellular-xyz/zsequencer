import asyncio
import json
import os
import sys
from typing import Any, Dict, List

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

import requests
from pyfrost.network_http.dkg import Dkg

from config import zconfig
from zsequencer.sequencer import tss


async def run_sample() -> None:
    nodes_info: tss.NodesInfo = tss.NodesInfo()
    all_nodes: List[str] = nodes_info.get_all_nodes()
    dkg: Dkg = Dkg(nodes_info, default_timeout=50)
    dk: Dict[str, Any] = await dkg.request_dkg(zconfig.THRESHOLD_NUMBER, all_nodes)
    data: Dict[str, Any] = {
        "public_key": dk["public_key"],
        "public_shares": dk["public_shares"],
        "party": dk["party"],
    }
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    for node in zconfig.NODES.values():
        url: str = f'http://{node["host"]}:{node["server_port"]}/node/distributed_keys'
        requests.put(url, json.dumps(data), headers=headers)
    print("Successfully initialized: ", dk)


if __name__ == "__main__":
    sys.set_int_max_str_digits(0)
    asyncio.run(run_sample())
