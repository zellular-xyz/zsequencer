import hashlib
import time
from collections import Counter
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Tuple

from eth_account.datastructures import SignedMessage
from eth_account.messages import SignableMessage, encode_defunct
from web3 import Account

from config import zconfig

from . import errors, response_utils

Decorator = Callable[[Callable[..., Any]], Callable[..., Any]]


def sequencer_only(f: Callable[..., Any]) -> Decorator:
    @wraps(f)
    def decorated_function(*args: Any, **kwargs: Any) -> Any:
        if zconfig.NODE["id"] != zconfig.SEQUENCER["id"]:
            return response_utils.error_response(errors.ErrorCodes.IS_NOT_SEQUENCER)
        return f(*args, **kwargs)

    return decorated_function


def not_sequencer(f: Callable[..., Any]) -> Decorator:
    @wraps(f)
    def decorated_function(*args: Any, **kwargs: Any) -> Any:
        if zconfig.NODE["id"] == zconfig.SEQUENCER["id"]:
            return response_utils.error_response(errors.ErrorCodes.IS_SEQUENCER)
        return f(*args, **kwargs)

    return decorated_function


def is_frost_sig_verified(sig: str, index: int, chaining_hash: str) -> bool:
    # TODO: check signature
    return True


def sign(msg: str) -> str:
    message_encoded: SignableMessage = encode_defunct(text=msg)
    sig: SignedMessage = Account.sign_message(
        message_encoded, private_key=int(zconfig.NODE["private_key"])
    )
    return sig.signature.hex()


def is_sig_verified(sig: str, node_id: str, msg: str) -> bool:
    try:
        msg_encoded: SignableMessage = encode_defunct(text=msg)
        recovered_address: str = Account.recover_message(msg_encoded, signature=sig)
        return recovered_address.lower() == zconfig.NODES[node_id]["address"].lower()
    except Exception:
        return False


def validate_request(req_data: Dict[str, Any], required_keys: List[str]) -> str:
    if all(key in req_data for key in required_keys):
        return ""
    missing_keys: List[str] = [key for key in required_keys if key not in req_data]
    message: str = "Required keys are missing: " + ", ".join(missing_keys)
    return message


def get_next_sequencer_id(old_sequencer_id: str) -> str:
    sorted_nodes: List[Dict[str, Any]] = sorted(
        zconfig.NODES.values(), key=lambda x: x["id"]
    )
    index: Optional[int] = next(
        (i for i, item in enumerate(sorted_nodes) if item["id"] == old_sequencer_id),
        None,
    )
    if index is None or index == len(sorted_nodes) - 1:
        return sorted_nodes[0]["id"]
    else:
        return sorted_nodes[index + 1]["id"]


def is_switch_approved(proofs: List[Dict[str, Any]]) -> bool:
    approvals: int = sum(1 for proof in proofs if is_dispute_approved(proof))
    return approvals >= zconfig.THRESHOLD_NUMBER


def is_dispute_approved(proof: Dict[str, Any]) -> bool:
    required_keys: List[str] = [
        "node_id",
        "old_sequencer_id",
        "new_sequencer_id",
        "timestamp",
        "sig",
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

    if not is_sig_verified(
        proof["sig"],
        proof["node_id"],
        f'{zconfig.SEQUENCER["id"]}{proof["timestamp"]}',
    ):
        return False

    return True


def get_switch_parameter_from_proofs(
    proofs: List[Dict[str, Any]],
) -> Tuple[Optional[str], Optional[str]]:
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
    else:
        return None, None


def gen_hash(s: str):
    return hashlib.sha256(s.encode()).hexdigest()
