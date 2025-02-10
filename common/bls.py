"""
Module for handling BLS signatures and related operations.
"""

import asyncio
import json
from typing import Any, Dict, Set, Optional

import requests
from eigensdk.crypto.bls import attestation

from config import zconfig
from . import utils
from .logger import zlogger


def bls_sign(message: str) -> str:
    """Sign a message using BLS."""
    signature: attestation.Signature = zconfig.NODE["bls_key_pair"].sign_message(
        message.encode("utf-8")
    )
    return signature.getStr(10).decode("utf-8")


def get_signers_aggregated_public_key(
        nonsigners: list[str], aggregated_public_key: attestation.G2Point
) -> attestation.G2Point:
    """Generate aggregated public key of the signers."""
    for nonsigner in nonsigners:
        non_signer_public_key: attestation.G2Point = zconfig.NODES[nonsigner]["public_key_g2"]
        aggregated_public_key = aggregated_public_key - non_signer_public_key
    return aggregated_public_key


def is_bls_sig_verified(
        signature_hex: str, message: str, public_key: attestation.G2Point
) -> bool:
    """Verify a BLS signature."""
    signature: attestation.Signature = attestation.new_zero_signature()
    signature.setStr(signature_hex.encode("utf-8"))
    return signature.verify(public_key, message.encode("utf-8"))


async def gather_signatures(
        sign_tasks: dict[asyncio.Task, str]
) -> dict[str, Any] | None:
    """Gather signatures from nodes until the stake of nodes reaches the threshold"""
    completed_results = {}
    pending_tasks = list(sign_tasks.keys())
    stake_percent = 100 * zconfig.NODE['stake'] / zconfig.TOTAL_STAKE
    try:
        while stake_percent < zconfig.THRESHOLD_PERCENT:
            done, pending_tasks = await asyncio.wait(pending_tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if not task.result():
                    continue
                node_id = sign_tasks[task]
                completed_results[node_id] = task.result()
                stake_percent += 100 * zconfig.NODES[node_id]['stake'] / zconfig.TOTAL_STAKE

    except Exception as error:
        if not isinstance(error, ValueError):  # For empty list
            zlogger.exception(f"An unexpected error occurred: {error}")
    return completed_results, stake_percent


def gather_and_aggregate_signatures(
        data: Dict[str, Any],
        node_ids: Set[str]
) -> Optional[Dict[str, Any]]:
    """
    Gather and aggregate signatures from nodes synchronously.
    Lock NODES and TAG and other zconfig.
    """
    tag = zconfig.NETWORK_STATUS_TAG
    network_state = zconfig.get_network_state(tag)
    node_info, network_nodes_info, total_stake = (
        zconfig.NODE,
        network_state.nodes,
        network_state.total_stake,
    )

    # Calculate total stake
    stake = sum([network_nodes_info[node_id]['stake'] for node_id in node_ids]) + node_info['stake']
    if 100 * stake / total_stake < zconfig.THRESHOLD_PERCENT:
        return None

    # Ensure all node_ids are valid
    if not node_ids.issubset(set(network_nodes_info.keys())):
        return None

    # Generate the message hash
    message: str = utils.gen_hash(json.dumps(data, sort_keys=True))

    # Synchronously request signatures from each node
    signatures: Dict[str, Dict[str, Any]] = {}
    for node_id in node_ids:
        try:
            signature_data = request_signature(
                node_id=node_id,
                url=f'{network_nodes_info[node_id]["socket"]}/node/sign_sync_point',
                data=data,
                message=message,
                timeout=120,
            )
            if signature_data:
                signatures[node_id] = signature_data
        except Exception as e:
            zlogger.exception(f"Failed to request signature from node {node_id}: {e}")

    # Calculate the stake percentage of the collected signatures
    collected_stake = sum([network_nodes_info[node_id]['stake'] for node_id in signatures.keys()])
    stake_percent = 100 * (collected_stake + node_info['stake']) / total_stake

    if stake_percent < zconfig.THRESHOLD_PERCENT:
        return None

    # Add the local node's signature
    data["signature"] = bls_sign(message)
    signatures[node_info['id']] = data

    # Identify nonsigners
    nonsigners = list(set(network_nodes_info.keys()) - set(signatures.keys()))

    # Generate the aggregated signature
    aggregated_signature: str = gen_aggregated_signature(list(signatures.values()))

    zlogger.info(f"data: {data}, message: {message}, nonsigners: {nonsigners}")
    return {
        "message": message,
        "signature": aggregated_signature,
        "nonsigners": nonsigners,
        'tag': tag,
    }


def request_signature(
        node_id: str, url: str, data: Dict[str, Any], message: str, timeout: int = 120
) -> Dict[str, Any] | None:
    """Request a signature from a node."""
    try:
        response = requests.post(url, json=data, timeout=timeout, headers=zconfig.HEADERS)
        response_json = response.json()

        if response_json.get("status") != "success":
            return None

        signature: attestation.Signature = attestation.new_zero_signature()
        signature.setStr(response_json["data"]["signature"].encode("utf-8"))

        if not signature.verify(
                pub_key=zconfig.NODES[node_id]["public_key_g2"],
                msg_bytes=message.encode("utf-8"),
        ):
            return None

        return response_json["data"]

    except requests.Timeout:
        zlogger.warning(f"Requesting signature from {node_id} timeout.")
    except Exception as e:
        zlogger.exception(f"An unexpected error occurred requesting signature from {node_id}:")

    return None


def gen_aggregated_signature(signatures: list[dict[str, Any] | None]) -> str:
    """Aggregate individual signatures into a single signature."""
    aggregated_signature: attestation.Signature = attestation.new_zero_signature()
    for signature in signatures:
        if not signature:
            continue
        sig: attestation.Signature = attestation.new_zero_signature()
        sig.setStr(signature["signature"].encode("utf-8"))
        aggregated_signature = aggregated_signature + sig

    return aggregated_signature.getStr(10).decode("utf-8")
