"""
Module for handling BLS signatures and related operations.
"""

import asyncio
import json
from typing import Any

import aiohttp
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


def get_signers_aggregated_public_key(nonsigners: list[str]) -> attestation.G2Point:
    """Generate aggregated public key of the signers."""
    aggregated_public_key: attestation.G2Point = zconfig.AGGREGATED_PUBLIC_KEY
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
    completed_results = []
    pending_tasks = list(sign_tasks.keys())
    stake_percent = 0
    try:
        while stake_percent < zconfig.THRESHOLD_PERCENT:
            done, pending = await asyncio.wait(pending_tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                completed_results.append(task.result())
                if not task.result():
                    continue
                node_id = sign_tasks[task]
                stake_percent += 100 * zconfig.NODES[node_id]['stake'] / zconfig.TOTAL_STAKE
            pending_tasks = pending
        return completed_results
    except ValueError:
        return completed_results
    except Exception as error:
        zlogger.exception(f"An unexpected error occurred: {error}")
        return completed_results
    
async def gather_and_aggregate_signatures(
    data: dict[str, Any], node_ids: set[str]
) -> dict[str, Any] | None:
    """Gather and aggregate signatures from nodes."""
    stake = sum([zconfig.NODES[node_id]['stake'] for node_id in node_ids])
    stake += zconfig.NODE['stake']
    if 100 * stake / zconfig.TOTAL_STAKE < zconfig.THRESHOLD_PERCENT:
        return None

    if not node_ids.issubset(set(zconfig.NODES.keys())):
        return None

    message: str = utils.gen_hash(json.dumps(data, sort_keys=True))

    sign_tasks: dict[asyncio.Task, str] = {
        asyncio.create_task(
            request_signature(
                node_id=node_id,
                url=f'http://{zconfig.NODES[node_id]["host"]}:{zconfig.NODES[node_id]["port"]}/node/sign_sync_point',
                data=data,
                message=message,
                timeout=120,
            )
        ) : node_id 
        for node_id in node_ids
    }
    try:
        completed_results = await asyncio.wait_for(gather_signatures(sign_tasks), timeout=zconfig.AGGREGATION_TIMEOUT)
    except asyncio.TimeoutError:
        zlogger.exception(f"Aggregation of signatures timed out after {zconfig.AGGREGATION_TIMEOUT} seconds.")
        return None
    
    signatures: list[dict[str, Any] | None] = completed_results
    signatures_dict: dict[str, dict[str, Any] | None] = dict(zip(node_ids, signatures))
    nonsigners = [k for k, v in signatures_dict.items() if v is None]
    nonsigners += list(set(zconfig.NODES.keys()) - node_ids - set(zconfig.NODE["id"]))
    nonsigners_stake = sum([zconfig.NODES[node_id]['stake'] for node_id in nonsigners])
    if 100 * nonsigners_stake / zconfig.TOTAL_STAKE > 100 - zconfig.THRESHOLD_PERCENT:
        return None

    data["signature"] = bls_sign(message)
    signatures.append(data)

    aggregated_signature: str = gen_aggregated_signature(
        [sig for sig in signatures if sig]
    )

    return {
        "message": message,
        "signature": aggregated_signature,
        "nonsigners": nonsigners,
    }


async def request_signature(
    node_id: str, url: str, data: dict[str, Any], message: str, timeout: int = 120
) -> dict[str, Any] | None:
    """Request a signature from a node."""
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=data, timeout=timeout) as response:
                response_json = await response.json()
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

        except asyncio.TimeoutError:
            zlogger.exception("Request timeout:")
        except Exception:
            zlogger.exception("An unexpected error occurred:")
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
