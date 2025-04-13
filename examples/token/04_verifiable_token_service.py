import logging
import json
from threading import Thread
from typing import Any
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from eth_account import Account
from eth_account.messages import encode_defunct
from starlette.responses import JSONResponse
from blspy import PopSchemeMPL, PrivateKey
from zellular import Zellular

app = FastAPI()

# Uncomment the desired node's private key and port
# NODE_PRIVATE_KEY, PORT = ('5b009195821da22cf90f375db7ee2dcf698791a5190a0b50dda3af653ee67d9b', 5001)
NODE_PRIVATE_KEY, PORT = ('53217fdb58315338ab035f6939b9c684ca54ec7fa7da2f78cf9583af5799fb40', 5002)
# NODE_PRIVATE_KEY, PORT = ('7126ea0f6c7acb39d30ce7fde262a8a1fc53f5d994ef03be265d65bf370ad184', 5003)

# Initialize BLS private key
sk = PrivateKey.from_bytes(bytes.fromhex(NODE_PRIVATE_KEY))

# Initialize Logger
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Initialize Zellular
zellular = Zellular("token", "http://37.27.41.237:6001/", threshold_percent=1)

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

    txs = [{
        "sender": data.sender,
        "receiver": data.receiver,
        "amount": data.amount,
        "signature": data.signature
    }]

    zellular.send(txs, blocking=False)
    return JSONResponse({"message": "Transfer sent"})

def apply_transfer(data: dict[str, Any]) -> None:
    """Executes a transfer after batch processing."""
    sender, receiver, amount, signature = (
        data["sender"], data["receiver"], data["amount"], data["signature"]
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

# -- start: checking balance --
@app.get("/balance")
async def balance(address: str) -> dict[str, Any]:
    """Retrieves the balance of a given address and returns a BLS-signed message."""
    balance = balances.get(address, 0)
    message = f"Address: {address}, Balance: {balance}".encode("utf-8")
    signature = PopSchemeMPL.sign(sk, message)
    return {"address": address, "balance": balance, "signature": str(signature)}
# -- end: checking balance --

def process_loop() -> None:
    """Continuously processes incoming batches from Zellular."""
    for batch, index in zellular.batches():
        txs = json.loads(batch)
        for tx in txs:
            apply_transfer(tx)

if __name__ == "__main__":
    Thread(target=process_loop, daemon=True).start()
    import uvicorn
    uvicorn.run(app, port=PORT)
