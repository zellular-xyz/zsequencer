"""This module provides utility functions and decorators for the zellular application."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, as_completed

import xxhash
from eth_account.messages import SignableMessage, encode_defunct
from fastapi import Request
from web3 import Account

from common.errors import (
    InvalidNodeVersionError,
    IsNotSequencerError,
    IsPausedError,
    IsSequencerError,
    NotSyncedError,
)
from config import zconfig


def sequencer_only(request: Request) -> None:
    """Decorator to restrict access to sequencer-only functions."""
    if zconfig.NODE["id"] != zconfig.SEQUENCER["id"]:
        raise IsNotSequencerError()


def not_sequencer(request: Request) -> None:
    """Decorator to restrict access to non-sequencer functions."""
    if zconfig.NODE["id"] == zconfig.SEQUENCER["id"]:
        raise IsSequencerError()


def validate_version(role: str) -> Callable[[Request], None]:
    """Decorator to validate the 'Version' header against the expected version.

    Checks if the request's 'Version' header matches zconfig.VERSION for endpoints
    starting with 'sequencer' or 'node'. Returns an error response if validation fails.
    """

    def validator(request: Request) -> None:
        version = request.headers.get("Version", "")
        cond1 = (not version or version != zconfig.VERSION) and role == "sequencer"
        cond2 = version and version != zconfig.VERSION and role == "node"
        if cond1 or cond2:
            raise InvalidNodeVersionError()

    return validator


def is_synced(request: Request) -> None:
    """Decorator to ensure the app is synced with sequencer (leader) before processing the request."""
    if not zconfig.get_synced_flag():
        raise NotSyncedError()


def not_paused(request: Request) -> None:
    """Decorator to ensure the service is not paused."""
    if zconfig.is_paused:
        raise IsPausedError()


def eth_sign(message: str) -> str:
    """Sign a message using the node's private key."""
    message_encoded: SignableMessage = encode_defunct(text=message)
    account_instance: Account = Account()
    return account_instance.sign_message(
        signable_message=message_encoded,
        private_key=zconfig.NODE["ecdsa_private_key"],
    ).signature.hex()


def is_eth_sig_verified(signature: str, node_id: str, message: str) -> bool:
    """Verify a signature against the node's public address."""
    try:
        msg_encoded: SignableMessage = encode_defunct(text=message)
        account_instance: Account = Account()
        recovered_address: str = account_instance.recover_message(
            signable_message=msg_encoded,
            signature=signature,
        )
        return recovered_address.lower() == zconfig.NODES[node_id]["address"].lower()
    except Exception:
        return False


def gen_hash(message: str) -> str:
    """Generate a hash for a given string."""
    return xxhash.xxh128_hexdigest(message)


def multi_gen_hash(strings: list[str]) -> list[str]:
    """Generate hashes for multiple strings concurrently."""
    with ProcessPoolExecutor() as executor:
        futures = {executor.submit(gen_hash, s): i for i, s in enumerate(strings)}
        results = [""] * len(strings)
        for future in as_completed(futures):
            index = futures[future]
            results[index] = future.result()
    return results


def get_utf8_size_bytes(text: str) -> int:
    return len(text.encode("utf-8"))


def get_utf8_size_kb(text: str) -> float:
    return get_utf8_size_bytes(text) / 1024
