import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import argparse

from config import zconfig
from zsequencer.sequencer import tss

if __name__ == "__main__":
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Run Frost node"
    )
    parser.add_argument(
        "node_id", choices=list(zconfig.NODES.keys()), help="The frost node id"
    )
    args: argparse.Namespace = parser.parse_args()

    tss.run(args.node_id)
