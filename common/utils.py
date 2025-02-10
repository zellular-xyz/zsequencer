"""This module provides utility functions and decorators for the zellular application."""

import time
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, as_completed
from functools import wraps
from typing import Any

import xxhash
from eth_account.messages import SignableMessage, encode_defunct
from flask import request
from web3 import Account


from config import zconfig
from . import errors, response_utils

Decorator = Callable[[Callable[..., Any]], Callable[..., Any]]


def sequencer_only(func: Callable[..., Any]) -> Decorator:
    """Decorator to restrict access to sequencer-only functions."""

    @wraps(func)
    def decorated_function(*args: Any, **kwargs: Any) -> Any:
        if zconfig.NODE["id"] != zconfig.SEQUENCER["id"]:
            return response_utils.error_response(errors.ErrorCodes.IS_NOT_SEQUENCER)
        return func(*args, **kwargs)

    return decorated_function


def not_sequencer(func: Callable[..., Any]) -> Decorator:
    """Decorator to restrict access to non-sequencer functions."""

    @wraps(func)
    def decorated_function(*args: Any, **kwargs: Any) -> Any:
        if zconfig.NODE["id"] == zconfig.SEQUENCER["id"]:
            return response_utils.error_response(errors.ErrorCodes.IS_SEQUENCER)
        return func(*args, **kwargs)

    return decorated_function


def validate_request(func: Callable[..., Any]) -> Decorator:
    """Decorator to validate the request."""

    @wraps(func)
    def decorated_function(*args: Any, **kwargs: Any) -> Any:
        version = request.headers.get("Version", "")
        if (not version or version != zconfig.VERSION) and \
                request.endpoint.startswith("sequencer"):
            return response_utils.error_response(errors.ErrorCodes.INVALID_NODE_VERSION,
                                                 errors.ErrorMessages.INVALID_NODE_VERSION)
        if (version and version != zconfig.VERSION) and \
                request.endpoint.startswith("node"):
            return response_utils.error_response(errors.ErrorCodes.INVALID_NODE_VERSION,
                                                 errors.ErrorMessages.INVALID_NODE_VERSION)
        if zconfig.IS_SYNCING and request.endpoint not in ["node.get_state", "node.get_last_finalized_batch",
                                                           "node.get_batches"]:
            return response_utils.error_response(errors.ErrorCodes.IS_SYNCING, errors.ErrorMessages.IS_SYNCING)
        return func(*args, **kwargs)

    return decorated_function


def eth_sign(message: str) -> str:
    """Sign a message using the node's private key."""
    message_encoded: SignableMessage = encode_defunct(text=message)
    account_instance: Account = Account()
    return account_instance.sign_message(
        signable_message=message_encoded, private_key=zconfig.NODE["ecdsa_private_key"]
    ).signature.hex()


def is_eth_sig_verified(signature: str, node_id: str, message: str) -> bool:
    """Verify a signature against the node's public address."""
    try:
        msg_encoded: SignableMessage = encode_defunct(text=message)
        account_instance: Account = Account()
        recovered_address: str = account_instance.recover_message(
            signable_message=msg_encoded, signature=signature
        )
        return recovered_address.lower() == zconfig.NODES[node_id]["address"].lower()
    except Exception:
        return False


def validate_keys(req_data: dict[str, Any], required_keys: list[str]) -> str:
    """Validate a request by checking if required keys are present."""
    if all(key in req_data for key in required_keys):
        return ""
    missing_keys: list[str] = [key for key in required_keys if key not in req_data]
    message: str = "Required keys are missing: " + ", ".join(missing_keys)
    return message


def get_next_sequencer_id(old_sequencer_id: str) -> str:
    """Get the ID of the next sequencer."""
    sorted_nodes: list[dict[str, Any]] = sorted(
        zconfig.NODES.values(), key=lambda x: x["id"]
    )
    index: int | None = next(
        (i for i, item in enumerate(sorted_nodes) if item["id"] == old_sequencer_id),
        None,
    )
    if index is None or index == len(sorted_nodes) - 1:
        return sorted_nodes[0]["id"]

    return sorted_nodes[index + 1]["id"]


def is_switch_approved(proofs: list[dict[str, Any]]) -> bool:
    """Check if the switch to a new sequencer is approved."""
    node_ids = [proof['node_id'] for proof in proofs if is_dispute_approved(proof)]
    stake = sum([zconfig.NODES[node_id]['stake'] for node_id in node_ids])
    return 100 * stake / zconfig.TOTAL_STAKE >= zconfig.THRESHOLD_PERCENT


def is_dispute_approved(proof: dict[str, Any]) -> bool:
    """Check if a dispute is approved based on the provided proof."""
    required_keys: list[str] = [
        "node_id",
        "old_sequencer_id",
        "new_sequencer_id",
        "timestamp",
        "signature",
    ]
    if not all(key in proof for key in required_keys):
        return False

    new_sequencer_id: str = get_next_sequencer_id(zconfig.SEQUENCER["id"])
    if (
            proof["old_sequencer_id"] != zconfig.SEQUENCER["id"]
            or proof["new_sequencer_id"] != new_sequencer_id
    ):
        return False

    now: float = time.time()
    if not now - 600 <= proof["timestamp"] <= now + 60:
        return False

    if not is_eth_sig_verified(
            signature=proof["signature"],
            node_id=proof["node_id"],
            message=f'{zconfig.SEQUENCER["id"]}{proof["timestamp"]}',
    ):
        return False

    return True


def get_switch_parameter_from_proofs(
        proofs: list[dict[str, Any]],
) -> tuple[str | None, str | None]:
    """Get the switch parameters from proofs."""
    sequencer_counts: Counter = Counter()
    for proof in proofs:
        if "old_sequencer_id" in proof and "new_sequencer_id" in proof:
            old_sequencer_id, new_sequencer_id = (
                proof["old_sequencer_id"],
                proof["new_sequencer_id"],
            )
            sequencer_counts[(old_sequencer_id, new_sequencer_id)] += 1

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
