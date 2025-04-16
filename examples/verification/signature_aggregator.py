import asyncio
import json
from dataclasses import dataclass
from typing import Any

import aiohttp
from blspy import G1Element, G2Element, PopSchemeMPL

# --- Config and constants ---
with open("nodes.json") as f:
    NODE_CONFIG: dict[str, dict[str, str]] = json.load(f)

REQUEST_TIMEOUT: int = 3
SIGNATURE_THRESHOLD: float = 2 / 3

# --- Structured response from each node ---


@dataclass
class BalanceResponse:
    node_id: str
    balance: int | None
    signature: str | None


# --- Network logic ---


async def fetch_signed_balance(
    session: aiohttp.ClientSession, node_id: str, url: str, address: str
) -> BalanceResponse:
    try:
        async with session.get(
            url, params={"address": address}, timeout=REQUEST_TIMEOUT
        ) as response:
            data: dict[str, Any] = await response.json()
            return BalanceResponse(node_id, data.get("balance"), data.get("signature"))
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return BalanceResponse(node_id, None, None)


async def request_balances_from_nodes(address: str) -> list[BalanceResponse]:
    async with aiohttp.ClientSession() as session:
        tasks = [
            fetch_signed_balance(session, node_id, node["url"], address)
            for node_id, node in NODE_CONFIG.items()
        ]
        return await asyncio.gather(*tasks)


# --- Signature aggregation ---


async def aggregate_valid_signatures(address: str) -> dict[str, Any]:
    node_responses = await request_balances_from_nodes(address)

    reported_balances: list[int] = [
        res.balance for res in node_responses if res.balance is not None
    ]

    if not reported_balances:
        raise ValueError("No valid balance responses received.")

    majority_balance: int = max(reported_balances, key=reported_balances.count)
    message: bytes = f"Address: {address}, Balance: {majority_balance}".encode("utf-8")

    verified_signatures: list[G2Element] = []
    failed_nodes: list[str] = []

    for res in node_responses:
        if res.balance != majority_balance:
            failed_nodes.append(res.node_id)
            continue

        try:
            pubkey = G1Element.from_bytes(
                bytes.fromhex(NODE_CONFIG[res.node_id]["pubkey"])
            )
            signature = G2Element.from_bytes(bytes.fromhex(res.signature))

            if not PopSchemeMPL.verify(pubkey, message, signature):
                failed_nodes.append(res.node_id)
                continue

            verified_signatures.append(signature)

        except Exception:
            failed_nodes.append(res.node_id)

    required_signatures = int(len(NODE_CONFIG) * SIGNATURE_THRESHOLD)

    if len(verified_signatures) < required_signatures:
        raise ValueError("Not enough valid signatures to reach the threshold.")

    aggregated_signature = PopSchemeMPL.aggregate(verified_signatures)

    return {
        "message": message.decode(),
        "aggregated_signature": str(aggregated_signature),
        "non_signing_nodes": failed_nodes,
    }


# --- Run it ---

if __name__ == "__main__":
    address_to_query: str = "0x2B3e5649A2Bfc3667b1db1A0ae7E1f9368d676A9"
    result: dict[str, Any] = asyncio.run(aggregate_valid_signatures(address_to_query))
    print(result)
