"""
Module for handling BLS signatures and related operations.
"""

import asyncio
import json
from typing import Any

import aiohttp
from eigensdk.crypto.bls import attestation

from zsequencer.config import zconfig

from . import utils
from .logger import zlogger


def bls_sign(message: str) -> str:
    """Sign a message using BLS."""
    signature: attestation.Signature = zconfig.NODE["key_pair"].sign_message(
        message.encode("utf-8")
    )
    return signature.getStr(10).decode("utf-8")


def get_signers_aggregated_public_key(nonsigners: list[str]) -> attestation.G2Point:
    """Generate aggregated public key of the signers."""
    aggregated_public_key: attestation.G2Point = zconfig.AGGREGATED_PUBLIC_KEY
    for nonsigner in nonsigners:
        non_signer_public_key: attestation.G2Point = attestation.new_zero_g2_point()
        non_signer_public_key.setStr(nonsigner.encode("utf-8"))
        aggregated_public_key = aggregated_public_key - non_signer_public_key
    return aggregated_public_key


def is_bls_sig_verified(
    signature_hex: str, message: str, public_key: attestation.G2Point
) -> bool:
    """Verify a BLS signature."""
    signature: attestation.Signature = attestation.new_zero_signature()
    signature.setStr(signature_hex.encode("utf-8"))
    return signature.verify(public_key, message.encode("utf-8"))


async def gather_and_aggregate_signatures(
    data: dict[str, Any], node_ids: set[str]
) -> dict[str, Any] | None:
    """Gather and aggregate signatures from nodes."""
    if len(node_ids) < zconfig.THRESHOLD_NUMBER:
        return None

    if not node_ids.issubset(set(zconfig.NODES.keys())):
        return None

    message: str = utils.gen_hash(json.dumps(data, sort_keys=True))

    tasks: list[asyncio.Task] = [
        asyncio.create_task(
            request_signature(
                node_id=node_id,
                url=f'http://{zconfig.NODES[node_id]["host"]}:{zconfig.NODES[node_id]["port"]}/node/sign_sync_point',
                data=data,
                message=message,
                timeout=120,
            )
        )
        for node_id in node_ids
    ]
    signatures: list[dict[str, Any] | None] = await asyncio.gather(*tasks)
    signatures_dict: dict[str, dict[str, Any] | None] = dict(zip(node_ids, signatures))
    nonsigners = [k for k, v in signatures_dict.items() if v is None]
    if len(signatures) - len(nonsigners) + 1 < zconfig.THRESHOLD_NUMBER:
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
