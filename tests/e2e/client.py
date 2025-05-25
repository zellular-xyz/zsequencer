import argparse
import json
import os
import random
import time
from uuid import uuid4

from zellular import StaticNetwork, Zellular

from common.errors import IsSequencerError
from common.logger import zlogger
from tests.e2e.run import SIMULATION_DATA_DIR, load_simulation_config


def is_sequencer_error(e: Exception) -> bool:
    try:
        return e.response.json()["error"]["code"] == IsSequencerError.__name__
    except Exception:
        return False


def main(config_path: str) -> None:
    config = load_simulation_config(config_path)

    with open(os.path.join(SIMULATION_DATA_DIR, "nodes.json")) as f:
        nodes = json.load(f)

    sequencer_port = None
    network = StaticNetwork(
        nodes,
        threshold_percent=config.shared_env_variables["ZSEQUENCER_THRESHOLD_PERCENT"],
    )
    while True:
        time.sleep(1)
        port = config.base_port + random.randint(1, config.node_num)
        if port == sequencer_port:
            continue
        gateway = f"http://localhost:{port}"
        zellular = Zellular(
            app="simple_app", network=network, gateway=gateway, timeout=2
        )
        t = int(time.time())
        txs = [{"tx_id": str(uuid4()), "operation": "foo", "t": t} for i in range(1)]
        try:
            zellular.send(json.dumps(txs))
        except Exception as e:
            if is_sequencer_error(e):
                sequencer_port = port
                zlogger.warning(
                    f"Port {port} is used by sequencer. No request will be sent to the sequencer anymore."
                )
            else:
                zlogger.error(e)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run a zsequencer client")
    parser.add_argument(
        "--config",
        type=str,
        default="tests/e2e/sample_config.json",
        help="Path to the simulation configuration file",
    )

    args = parser.parse_args()
    main(args.config)
