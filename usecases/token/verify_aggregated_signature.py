import json
from blspy import G1Element, G2Element, PopSchemeMPL

SIGNATURE_AGGREGATOR_RESULT = {
    'message': b'Address: 0x2B3e5649A2Bfc3667b1db1A0ae7E1f9368d676A9, Balance: 0',
    'aggregated_signature': 'b15aa39f782ce387a59efeb8c141f9ed66f1831b01788ceaf9b96620d4bc37fcaad94c47c7f346c7c5a2ef0f3ef85150031ffd443c470ef4de2bcfac5c50086f347c71c9c626ece3dcf1a0b056105200becc01ae885bccabf9f52c59e2201c84',
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
