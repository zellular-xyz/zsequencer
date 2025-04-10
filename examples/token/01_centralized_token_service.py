from fastapi import FastAPI, Request, HTTPException
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import JSONResponse
from pydantic import BaseModel
from typing import Any

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="supersecretkey")  # Use a strong secret key

# Simulated user database
users = {"user1": "pass1"}
balances = {"user1": 100}

# Define request models
class LoginRequest(BaseModel):
    username: str
    password: str

class TransferRequest(BaseModel):
    receiver: str
    amount: int

@app.post("/login")
async def login(request: Request, data: LoginRequest):
    """Authenticate user and store session."""
    if users.get(data.username) != data.password:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    request.session["username"] = data.username  # Store username in session
    return JSONResponse({"message": "Login successful"})

@app.post("/transfer")
async def transfer(request: Request, data: TransferRequest):
    """Transfer funds between users."""
    username = request.session.get("username")
    if not username:
        raise HTTPException(status_code=401, detail="Unauthorized")

    if balances.get(username, 0) < data.amount:
        raise HTTPException(status_code=400, detail="Insufficient balance")

    balances[username] -= data.amount
    balances[data.receiver] = balances.get(data.receiver, 0) + data.amount
    return JSONResponse({"message": "Transfer successful"})

@app.get("/balance")
async def balance(username: str) -> dict[str, Any]:
    """Retrieve user balance."""
    return {"username": username, "balance": balances.get(username, 0)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, port=5001)
