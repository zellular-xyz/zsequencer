import json
from blspy import G1Element, G2Element, PopSchemeMPL

SIGNATURE_AGGREGATOR_RESULT = {
    'message': b'Address: 0x2B3e5649A2Bfc3667b1db1A0ae7E1f9368d676A9, Balance: 10',
    'aggregated_signature': '8a91b929d8d8d67324ed34e15a181f0143e81ca70c4677fb720bf855f2a82bdac020ceea9d873655354b4aa5ccfc113510691a476df4ed2bcfbace9ce12689785613a0f0d2913eb5bf12e57a3da6872e93ede923e8b13a464203b8ee1d71aa9b',
    'non_signing_nodes': ['Node3']
}

# List of nodes and their public keys
with open('nodes.json') as f:
    NODE_CONFIG = json.loads(f.read())

# Configurations
SIGNATURE_THRESHOLD = 2 / 3  # At least 2/3 of nodes must agree
TOTAL_NODES = len(NODE_CONFIG)  # Total number of nodes

# Aggregated public key for all nodes in the token service
AGGREGATE_PUBLIC_KEY_HEX = "a95b5b00610160521fc0a34bf5bc3e9c4e4b81ca10a99731de2291ad34f07224e16581c195d1452dfd75876c973853a1"
aggregated_pubkey = G1Element.from_bytes(bytes.fromhex(AGGREGATE_PUBLIC_KEY_HEX))

# Get the list of non-signing nodes
non_signing_nodes = SIGNATURE_AGGREGATOR_RESULT["non_signing_nodes"]

# Check if the threshold is met
required_signers = int(TOTAL_NODES * SIGNATURE_THRESHOLD)
actual_signers = TOTAL_NODES - len(non_signing_nodes)

if actual_signers < required_signers:
    raise ValueError(f"Not enough valid signatures! Required: {required_signers}, Got: {actual_signers}")

# Subtract non-signing nodes' public keys from the aggregate public key
for node_id in non_signing_nodes:
    node_pubkey = G1Element.from_bytes(bytes.fromhex(NODE_CONFIG[node_id]["pubkey"])).negate()
    aggregated_pubkey += node_pubkey  # Equivalent to subtraction

# Deserialize aggregated signature
aggregated_signature = G2Element.from_bytes(bytes.fromhex(SIGNATURE_AGGREGATOR_RESULT["aggregated_signature"]))

# Verify the aggregated signature against the adjusted public key
is_valid = PopSchemeMPL.verify(aggregated_pubkey, SIGNATURE_AGGREGATOR_RESULT["message"], aggregated_signature)

# Output result
print("Signature Valid:", is_valid)
