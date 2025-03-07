import json
import asyncio
import aiohttp
from blspy import G1Element, G2Element, PopSchemeMPL

# Configuration of nodes and their public keys
with open('nodes.json') as f:
    NODE_CONFIG = json.loads(f.read())

REQUEST_TIMEOUT = 3  # Timeout in seconds for balance requests
SIGNATURE_THRESHOLD = 2 / 3  # At least 2/3 of nodes must agree


async def fetch_signed_balance(session, node_id, url, address):
    """Fetch balance and BLS signature from a node."""
    try:
        async with session.get(url, params={'address': address}, timeout=REQUEST_TIMEOUT) as response:
            data = await response.json()
            return node_id, data.get("balance"), data.get("signature")
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return node_id, None, None  # Node did not respond


async def request_balances_from_nodes(address):
    """Query all nodes asynchronously for signed balances."""
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_signed_balance(session, node_id, node["url"], address) for node_id, node in NODE_CONFIG.items()]
        return await asyncio.gather(*tasks)


async def aggregate_valid_signatures(address):
    """Aggregate valid BLS signatures from nodes that agree on the majority balance."""
    node_responses = await request_balances_from_nodes(address)

    # Collect balances, ignoring failed responses
    reported_balances = [balance for _, balance, _ in node_responses if balance is not None]

    if not reported_balances:
        raise ValueError("No valid balance responses received.")

    # Identify the most commonly reported balance (majority balance)
    majority_balance = max(reported_balances, key=reported_balances.count)

    message = f"Address: {address}, Balance: {majority_balance}".encode('utf-8')
    verified_signatures, failed_nodes = [], []

    # Process responses: Verify signatures and collect valid ones
    for node_id, balance, signature_hex in node_responses:
        if balance is None or balance != majority_balance:
            failed_nodes.append(node_id)
            continue

        try:
            pubkey = G1Element.from_bytes(bytes.fromhex(NODE_CONFIG[node_id]["pubkey"]))
            signature = G2Element.from_bytes(bytes.fromhex(signature_hex))

            if not PopSchemeMPL.verify(pubkey, message, signature):
                failed_nodes.append(node_id)
                continue

            verified_signatures.append(signature)

        except Exception:
            failed_nodes.append(node_id)

    # Ensure we have enough valid signatures for aggregation
    valid_signature_count = len(verified_signatures)
    required_signatures = int(len(NODE_CONFIG) * SIGNATURE_THRESHOLD)

    if valid_signature_count < required_signatures:
        raise ValueError("Not enough valid signatures to reach the threshold.")

    # Aggregate the valid signatures
    aggregated_signature = PopSchemeMPL.aggregate(verified_signatures)

    return {
        "message": message,
        "aggregated_signature": str(aggregated_signature),
        "non_signing_nodes": failed_nodes
    }


address_to_query = "0x2B3e5649A2Bfc3667b1db1A0ae7E1f9368d676A9"
res = asyncio.run(aggregate_valid_signatures(address_to_query))
print(res)