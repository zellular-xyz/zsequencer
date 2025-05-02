import json
from typing import Any
from blspy import G1Element, G2Element, PopSchemeMPL

# --- Load result from the aggregator ---
AGGREGATED_RESPONSE: dict[str, Any] = {
    "address": "0x2B3e5649A2Bfc3667b1db1A0ae7E1f9368d676A9",
    "balance": 10,
    "aggregated_signature": (
        "8a91b929d8d8d67324ed34e15a181f0143e81ca70c4677fb720bf855f2a82bdac020ceea9d873655354b4aa5ccfc1135"
        "10691a476df4ed2bcfbace9ce12689785613a0f0d2913eb5bf12e57a3da6872e93ede923e8b13a464203b8ee1d71aa9b"
    ),
    "non_signing_nodes": ["Node3"],
}

# --- Load node config ---
with open("nodes.json") as f:
    NODE_CONFIG: dict[str, dict[str, str]] = json.load(f)

# --- Reconstruct Message ---
address = AGGREGATED_RESPONSE["address"]
balance = AGGREGATED_RESPONSE["balance"]
message: bytes = f"Address: {address}, Balance: {balance}".encode("utf-8")

# --- Aggregate Public Key ---
AGGREGATE_PUBLIC_KEY_HEX = "a95b5b00610160521fc0a34bf5bc3e9c4e4b81ca10a99731de2291ad34f07224e16581c195d1452dfd75876c973853a1"
aggregate_pubkey = G1Element.from_bytes(bytes.fromhex(AGGREGATE_PUBLIC_KEY_HEX))

# --- Subtract Non-Signers ---
for node_id in AGGREGATED_RESPONSE["non_signing_nodes"]:
    pubkey = G1Element.from_bytes(bytes.fromhex(NODE_CONFIG[node_id]["pubkey"]))
    aggregate_pubkey += pubkey.negate()  # Subtract non-signers

# --- Parse Signature ---
aggregated_signature = G2Element.from_bytes(
    bytes.fromhex(AGGREGATED_RESPONSE["aggregated_signature"])
)

# --- Verify ---
is_valid = PopSchemeMPL.verify(aggregate_pubkey, message, aggregated_signature)
print("Aggregated Signature Valid:", is_valid)
