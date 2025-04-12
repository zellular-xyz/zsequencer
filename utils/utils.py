import json
import os

import requests

from typing import List
from schema import NodeSource


def get_file_content(source: str) -> str:
    """Get the json contents of a file"""
    if source.startswith("http://") or source.startswith("https://"):
        response = requests.get(source)
        response.raise_for_status()
        return response.json()
    elif os.path.isfile(source):
        with open(source, "r", encoding="utf-8") as file:
            content = json.loads(file.read())
        return content
    else:
        raise ValueError(
            "The source provided is neither a valid URL nor a valid file path."
        )


def validate_env_variables(source: NodeSource):
    """Validate that all required environment variables are set."""
    required_vars: list[str] = [
        "ZSEQUENCER_BLS_KEY_FILE",
        "ZSEQUENCER_BLS_KEY_PASSWORD",
        "ZSEQUENCER_ECDSA_KEY_FILE",
        "ZSEQUENCER_ECDSA_KEY_PASSWORD",
        "ZSEQUENCER_APPS_FILE",
        "ZSEQUENCER_SNAPSHOT_PATH",
        "ZSEQUENCER_PORT",
        "ZSEQUENCER_SNAPSHOT_CHUNK",
        "ZSEQUENCER_REMOVE_CHUNK_BORDER",
        "ZSEQUENCER_THRESHOLD_PERCENT",
        "ZSEQUENCER_SEND_BATCH_INTERVAL",
        "ZSEQUENCER_SYNC_INTERVAL",
        "ZSEQUENCER_FINALIZATION_TIME_BORDER",
        "ZSEQUENCER_SIGNATURES_AGGREGATION_TIMEOUT",
        "ZSEQUENCER_FETCH_APPS_AND_NODES_INTERVAL",
        "ZSEQUENCER_INIT_SEQUENCER_ID",
        "ZSEQUENCER_NODES_SOURCE",
    ]
    eigenlayer_vars: list[str] = [
        "ZSEQUENCER_SUBGRAPH_URL",
        "ZSEQUENCER_RPC_NODE",
        "ZSEQUENCER_REGISTRY_COORDINATOR",
        "ZSEQUENCER_OPERATOR_STATE_RETRIEVER",
    ]
    historical_nodes_snapshot_server_vars: List[str] = [
        "ZSEQUENCER_HISTORICAL_NODES_REGISTRY"
    ]

    if source == NodeSource.EIGEN_LAYER:
        required_vars.extend(eigenlayer_vars)
    elif source == NodeSource.FILE:
        required_vars.append("ZSEQUENCER_NODES_FILE")
    elif source == NodeSource.NODES_REGISTRY:
        required_vars.extend(historical_nodes_snapshot_server_vars)

    missing_vars: list[str] = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        raise EnvironmentError(
            f"Missing environment variables: {', '.join(missing_vars)}"
        )
