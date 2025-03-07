from typing import Dict, Any
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from eth_account import Account
from eth_account.messages import encode_defunct
from starlette.responses import JSONResponse

app = FastAPI()

# Simulated Balances
balances: Dict[str, int] = {"0xc66F8Fba940064B5bA8d437d6fF829E60134230E": 100}

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
    """Handles token transfers using signature-based authentication."""
    message = f"Transfer {data.amount} to {data.receiver}"

    if not verify_signature(data.sender, message, data.signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    if balances.get(data.sender, 0) < data.amount:
        raise HTTPException(status_code=400, detail="Insufficient balance")

    balances[data.sender] -= data.amount
    balances[data.receiver] = balances.get(data.receiver, 0) + data.amount
    return JSONResponse({"message": "Transfer successful"})

@app.get("/balance")
async def balance(address: str) -> Dict[str, Any]:
    """Retrieves the balance of a given address."""
    return {"address": address, "balance": balances.get(address, 0)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, port=5001)
