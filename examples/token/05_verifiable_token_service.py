import json
import logging
import aiohttp
import asyncio

from threading import Thread
from typing import Any

from blspy import PopSchemeMPL, PrivateKey, G1Element, G2Element
from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from starlette.responses import JSONResponse
from zellular import EigenlayerNetwork, Zellular

app = FastAPI()

# Uncomment the desired node's private key and port
NODE_PRIVATE_KEY, PORT, SELF_NODE_ID = (
    "5b009195821da22cf90f375db7ee2dcf698791a5190a0b50dda3af653ee67d9b",
    5001,
    "Node1",
)
# NODE_PRIVATE_KEY, PORT, SELF_NODE_ID = (
#     "53217fdb58315338ab035f6939b9c684ca54ec7fa7da2f78cf9583af5799fb40",
#     5002,
#     "Node2",
# )
# NODE_PRIVATE_KEY, PORT, SELF_NODE_ID = (
#     '7126ea0f6c7acb39d30ce7fde262a8a1fc53f5d994ef03be265d65bf370ad184',
#     5003,
#     "Node3",
# )

with open("nodes.json") as f:
    NODES: dict[str, dict[str, str]] = json.load(f)


# Aggregate public key of all nodes (precomputed offline)
AGGREGATE_PUBLIC_KEY_HEX = "a95b5b00610160521fc0a34bf5bc3e9c4e4b81ca10a99731de2291ad34f07224e16581c195d1452dfd75876c973853a1"
AGGREGATE_PUBLIC_KEY = G1Element.from_bytes(bytes.fromhex(AGGREGATE_PUBLIC_KEY_HEX))

# Initialize BLS private key
sk = PrivateKey.from_bytes(bytes.fromhex(NODE_PRIVATE_KEY))

# Initialize Logger
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Initialize Zellular
network = EigenlayerNetwork(
    subgraph_url="https://api.studio.thegraph.com/query/95922/avs-subgraph/v0.0.3",
    threshold_percent=40,
)
zellular = Zellular("token", network)

# Simulated Balances
balances: dict[str, int] = {"0xc66F8Fba940064B5bA8d437d6fF829E60134230E": 100}


def verify_signature(sender: str, message: str, signature: str) -> bool:
    """Verifies if the provided signature is valid for the given sender address."""
    try:
        message_hash = encode_defunct(text=message)
        recovered_address = Account.recover_message(message_hash, signature=signature)
        return recovered_address.lower() == sender.lower()
    except Exception:
        return False  # Any error in signature recovery means invalid signature


class TransferRequest(BaseModel):
    sender: str
    receiver: str
    amount: int
    signature: str


@app.post("/transfer")
async def transfer(data: TransferRequest) -> JSONResponse:
    """Handles token transfers using signature-based authentication and sends to Zellular."""
    message = f"Transfer {data.amount} to {data.receiver}"

    if not verify_signature(data.sender, message, data.signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    if balances.get(data.sender, 0) < data.amount:
        raise HTTPException(status_code=400, detail="Insufficient balance")

    txs = [
        {
            "sender": data.sender,
            "receiver": data.receiver,
            "amount": data.amount,
            "signature": data.signature,
        }
    ]

    zellular.send(txs, blocking=False)
    return JSONResponse({"message": "Transfer sent"})


def apply_transfer(data: dict[str, Any]) -> None:
    """Executes a transfer after batch processing."""
    sender, receiver, amount, signature = (
        data["sender"],
        data["receiver"],
        data["amount"],
        data["signature"],
    )

    message = f"Transfer {amount} to {receiver}"
    if not verify_signature(sender, message, signature):
        logger.error(f"Invalid signature: {data}")
        return

    if balances.get(sender, 0) < amount:
        logger.error(f"Insufficient balance: {data}")
        return

    balances[sender] -= amount
    balances[receiver] = balances.get(receiver, 0) + amount
    logger.info(f"Transfer successful: {data}")


def process_loop() -> None:
    """Continuously processes incoming batches from Zellular."""
    for batch, index in zellular.batches():
        txs = json.loads(batch)
        for tx in txs:
            apply_transfer(tx)


@app.get("/balance")
async def balance(address: str) -> dict[str, Any]:
    """Retrieves the balance of a given address and returns a BLS-signed message."""
    balance = balances.get(address, 0)
    message = f"Address: {address}, Balance: {balance}".encode("utf-8")
    signature = PopSchemeMPL.sign(sk, message)
    return {"address": address, "balance": balance, "signature": str(signature)}


# -- start: querying nodes for signed balances --
async def fetch_balance(
    session: aiohttp.ClientSession, node_id: str, node: dict[str, str], address: str
):
    try:
        async with session.get(
            f"{node['url']}/balance", params={"address": address}, timeout=3
        ) as response:
            data = await response.json()
            return node_id, data["balance"], data["signature"]
    except Exception:
        return node_id, None, None


async def query_nodes_for_balance(address: str):
    async with aiohttp.ClientSession() as session:
        tasks = [
            fetch_balance(session, node_id, node, address)
            for node_id, node in NODES.items()
            if node_id != SELF_NODE_ID
        ]
        return await asyncio.gather(*tasks)
# -- end: querying nodes for signed balances --

# -- start: aggregating matching signatures --
def aggregate_signatures(
    message: bytes, expected_value: int, results: list[tuple[str, int, str]]
):
    valid_sigs = []
    non_signers = []

    for node_id, value, sig_hex in results:
        if value != expected_value or sig_hex is None:
            non_signers.append(node_id)
            continue

        try:
            pubkey = G1Element.from_bytes(
                bytes.fromhex(NODES[node_id]["pubkey"])
            )
            sig = G2Element.from_bytes(bytes.fromhex(sig_hex))
            if PopSchemeMPL.verify(pubkey, message, sig):
                valid_sigs.append(sig)
            else:
                non_signers.append(node_id)
        except Exception:
            non_signers.append(node_id)

    if len(valid_sigs) < 2 * len(NODES) / 3:
        raise ValueError("Not enough valid signatures to reach threshold")

    return PopSchemeMPL.aggregate(valid_sigs), non_signers
# -- end: aggregating matching signatures --

# -- start: balance aggregation endpoint --
@app.get("/aggregate_balance")
async def aggregate_balance(address: str):
    local_balance = balances.get(address, 0)
    message = f"Address: {address}, Balance: {local_balance}".encode("utf-8")

    results = await query_nodes_for_balance(address)

    # Include self-signature
    self_signature = str(PopSchemeMPL.sign(sk, message))
    results.append((SELF_NODE_ID, local_balance, self_signature))

    try:
        aggregated_sig, non_signers = aggregate_signatures(
            message, local_balance, results
        )
    except ValueError:
        raise HTTPException(
            status_code=424, detail="Not enough valid signatures to aggregate balance"
        )

    return {
        "address": address,
        "balance": local_balance,
        "aggregated_signature": str(aggregated_sig),
        "non_signing_nodes": non_signers,
    }
# -- end: balance aggregation endpoint --

if __name__ == "__main__":
    Thread(target=process_loop, daemon=True).start()
    import uvicorn

    uvicorn.run(app, port=PORT)
