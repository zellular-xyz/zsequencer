import json
from blspy import G1Element, G2Element, PopSchemeMPL

# --- Type Annotations ---
from typing import Any

SIGNATURE_AGGREGATOR_RESULT: dict[str, Any] = {
    "message": b"Address: 0x2B3e5649A2Bfc3667b1db1A0ae7E1f9368d676A9, Balance: 10",
    "aggregated_signature": (
        "8a91b929d8d8d67324ed34e15a181f0143e81ca70c4677fb720bf855f2a82bdac020ceea9d873655354b4aa5ccfc1135"
        "10691a476df4ed2bcfbace9ce12689785613a0f0d2913eb5bf12e57a3da6872e93ede923e8b13a464203b8ee1d71aa9b"
    ),
    "non_signing_nodes": ["Node3"],
}

# --- Load node config and apply types ---
with open("nodes.json") as f:
    NODE_CONFIG: dict[str, dict[str, str]] = json.load(f)

# --- Config ---
SIGNATURE_THRESHOLD: float = 2 / 3
TOTAL_NODES: int = len(NODE_CONFIG)

# --- Aggregated Public Key ---
AGGREGATE_PUBLIC_KEY_HEX: str = (
    "a95b5b00610160521fc0a34bf5bc3e9c4e4b81ca10a99731de2291ad34f07224e16581c195d1452dfd75876c973853a1"
)
aggregated_pubkey: G1Element = G1Element.from_bytes(bytes.fromhex(AGGREGATE_PUBLIC_KEY_HEX))

# --- Non-signers and Threshold Check ---
non_signing_nodes: list[str] = SIGNATURE_AGGREGATOR_RESULT["non_signing_nodes"]
required_signers: int = int(TOTAL_NODES * SIGNATURE_THRESHOLD)
actual_signers: int = TOTAL_NODES - len(non_signing_nodes)

if actual_signers < required_signers:
    raise ValueError(f"Not enough valid signatures! Required: {required_signers}, Got: {actual_signers}")

# --- Subtract non-signing public keys from aggregate ---
for node_id in non_signing_nodes:
    node_pubkey: G1Element = G1Element.from_bytes(bytes.fromhex(NODE_CONFIG[node_id]["pubkey"])).negate()
    aggregated_pubkey += node_pubkey  # Equivalent to subtraction

# --- Verify Aggregated Signature ---
aggregated_signature: G2Element = G2Element.from_bytes(
    bytes.fromhex(SIGNATURE_AGGREGATOR_RESULT["aggregated_signature"])
)
message: bytes = SIGNATURE_AGGREGATOR_RESULT["message"]

is_valid: bool = PopSchemeMPL.verify(aggregated_pubkey, message, aggregated_signature)

# --- Output ---
print("Signature Valid:", is_valid)
