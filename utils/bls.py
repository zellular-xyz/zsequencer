from eigensdk.crypto.bls import attestation


def get_aggregated_public_key(nodes_data) -> attestation.G2Point:
    aggregated_public_key: attestation.G2Point = attestation.new_zero_g2_point()
    for _, node in nodes_data.items():
        if node["stake"] > 0:
            aggregated_public_key += node["public_key_g2"]
    return aggregated_public_key
