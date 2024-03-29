import json
import os
from typing import Any, Dict, Optional

from dotenv import load_dotenv

load_dotenv()

DB_NAME: str = "zellular_node"

RPC_URL: Optional[str] = os.getenv("ZAPP_RPC_URL")
SECRET_KEY: Optional[str] = os.getenv("ZAPP_SECRET_KEY")
PUBLIC_KEY: Optional[int] = int(os.getenv("ZAPP_PUBLIC_KEY") or 0)

NODES_FILE: str = "nodes.json"


def load_nodes(file_path: str) -> Dict[str, Dict[str, int]]:
    with open(file_path, "r") as json_file:
        nodes_data: Dict[str, Dict[str, int]] = json.load(json_file)
    return nodes_data


def update_sequencer(sequencer_id: Optional[str]) -> None:
    global SEQUENCER
    if sequencer_id:
        SEQUENCER = NODES[sequencer_id]


NODES: Dict[str, Dict[str, Any]] = load_nodes(NODES_FILE)


NODE: Dict[str, int] = next(
    (n for n in NODES.values() if n["public_key"] == PUBLIC_KEY), {}
)
NODE["private_key"] = int(os.getenv("ZAPP_PRIVATE_KEY") or 0)

SEQUENCER: Dict[str, Any] = NODES["1"]

NODES_NUMBERS: int = len(NODES)
THRESHOLD_NUMBER: int = 2

SEND_TXS_INTERVAL: int = 5
SYNC_INTERVAL: int = 30

MIN_NONCES: int = 10

FINALIZATION_TIME_BORDER: int = 120
