"""This module provides utility functions and decorators for the zellular application."""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import TYPE_CHECKING

import xxhash
from eth_account.messages import SignableMessage, encode_defunct
from fastapi import Request
from web3 import Account

from common.errors import (
    InvalidNodeVersionError,
    InvalidRequestError,
    IsNotSequencerError,
    IsPausedError,
    IsSequencerError,
    NotSyncedError,
    SequencerOutOfReachError,
)
from config import zconfig
from sequencer_sabotage_simulation import sequencer_sabotage_simulation_state

# Forward reference for type hints
if TYPE_CHECKING:
    from common.api_models import SwitchProof


def sequencer_simulation_malfunction(request: Request) -> None:
    if sequencer_sabotage_simulation_state.out_of_reach:
        raise SequencerOutOfReachError()


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


def validate_body_keys(required_keys: list[str]) -> Callable[[Request], None]:
    """Decorator to validate required keys in the request JSON body."""

    async def validator(request: Request) -> None:
        try:
            req_data = await request.json()
            if not isinstance(req_data, dict):
                raise InvalidRequestError("Request body must be a JSON object")

        except Exception:
            raise InvalidRequestError("Failed to parse JSON request body")

        if not all(key in req_data for key in required_keys):
            missing = [key for key in required_keys if key not in req_data]
            raise InvalidRequestError(
                f"Required keys are missing: {', '.join(missing)}"
            )

    return validator


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


def get_next_sequencer_id(old_sequencer_id: str) -> str:
    """Get the ID of the next sequencer in a circular sorted list."""
    sorted_nodes = sorted(
        zconfig.last_state.sequencing_nodes.values(), key=lambda x: x["id"]
    )

    ids = [node["id"] for node in sorted_nodes]

    try:
        index = ids.index(old_sequencer_id)
        return ids[(index + 1) % len(ids)]  # Circular indexing
    except ValueError:
        return ids[0]  # Default to first if old_sequencer_id is not found


def is_switch_approved(proofs: list["SwitchProof"]) -> bool:
    """Check if the switch to a new sequencer is approved."""
    node_ids = [proof.node_id for proof in proofs if is_dispute_approved(proof)]
    stake = sum([zconfig.NODES[node_id]["stake"] for node_id in node_ids])
    return 100 * stake / zconfig.TOTAL_STAKE >= zconfig.THRESHOLD_PERCENT


def is_dispute_approved(proof: "SwitchProof") -> bool:
    """Check if a dispute is approved based on the provided proof."""
    # Validate the proof logic
    expected_new_sequencer_id = get_next_sequencer_id(zconfig.SEQUENCER["id"])
    if (
        proof.old_sequencer_id != zconfig.SEQUENCER["id"]
        or proof.new_sequencer_id != expected_new_sequencer_id
    ):
        return False

    now = time.time()
    if not now - 600 <= proof.timestamp <= now + 60:
        return False

    if not is_eth_sig_verified(
        signature=proof.signature,
        node_id=proof.node_id,
        message=f"{zconfig.SEQUENCER['id']}{proof.timestamp}",
    ):
        return False

    return True


def get_switch_parameter_from_proofs(
    proofs: list[SwitchProof],
) -> tuple[str | None, str | None]:
    """Get the switch parameters from proofs."""
    sequencer_counts: Counter = Counter()
    for proof in proofs:
        sequencer_counts[(proof.old_sequencer_id, proof.new_sequencer_id)] += 1

    most_common_sequencer = sequencer_counts.most_common(1)
    if most_common_sequencer:
        return most_common_sequencer[0][0]

    return None, None


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
