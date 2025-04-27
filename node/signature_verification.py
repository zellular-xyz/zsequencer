import json

from eigensdk.crypto.bls import attestation

from common import bls, utils
from common.logger import zlogger
from config import zconfig


def _has_quorum(nonsigners_stake: int, total_stake: int):
    return 100 * nonsigners_stake / total_stake <= 100 - zconfig.THRESHOLD_PERCENT


def compute_signature_public_key(
        nodes_info,
        agg_pub_key,
        non_signers: list[str],
) -> attestation.G2Point:
    aggregated_public_key: attestation.G2Point = agg_pub_key
    for node_id in non_signers:
        aggregated_public_key -= nodes_info[node_id]["public_key_g2"]
    return aggregated_public_key


def is_sync_point_signature_verified(
        app_name: str,
        state: str,
        index: int,
        batch_hash: str,
        chaining_hash: str,
        tag: int,
        signature_hex: str,
        nonsigners: list[str],
) -> bool:
    """Should first load the state of network nodes info using signature tag

    Verify the BLS signature of a synchronization point.
    """
    network_state = zconfig.get_network_state(tag=tag)
    nodes_info = network_state.nodes

    nonsigners_stake = sum(
        [nodes_info.get(node_id, {}).get("stake", 0) for node_id in nonsigners],
    )
    agg_pub_key = compute_signature_public_key(
        nodes_info,
        network_state.aggregated_public_key,
        nonsigners,
    )

    if not _has_quorum(nonsigners_stake, network_state.total_stake):
        zlogger.error(
            f"Signature with invalid stake from sequencer tag: {tag}, index: {index}, nonsigners stake: {nonsigners_stake}, total stake: {zconfig.TOTAL_STAKE}",
        )
        return False

    data: str = json.dumps(
        {
            "app_name": app_name,
            "state": state,
            "index": index,
            "hash": batch_hash,
            "chaining_hash": chaining_hash,
        },
        sort_keys=True,
    )
    message: str = utils.gen_hash(data)
    zlogger.info(
        f"tag: {tag}, data: {data}, message: {message}, nonsigners: {nonsigners}",
    )
    return bls.is_bls_sig_verified(
        signature_hex=signature_hex,
        message=message,
        public_key=agg_pub_key,
    )
