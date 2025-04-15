from bisect import insort
from dataclasses import dataclass, field
from uuid import uuid4

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="supersecretkey")

# In-memory users
users = {"user1": "pass1", "user2": "pass2"}

# In-memory balances
balances: dict[str, dict[str, float]] = {
    "user1": {"USDT": 1000.0},
    "user2": {"ETH": 5.0},
}


@dataclass(order=True)
class OrderWrapper:
    sort_index: float
    order: dict = field(compare=False)


# Order book
order_book_wrapped: list[OrderWrapper] = []


# Login request schema
class LoginRequest(BaseModel):
    username: str
    password: str


# Order request schema
class OrderRequest(BaseModel):
    order_type: str  # 'buy' or 'sell'
    base_token: str
    quote_token: str
    quantity: float
    price: float


# --- Routes ---


@app.post("/login")
async def login(request: Request, data: LoginRequest):
    if users.get(data.username) != data.password:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    request.session["username"] = data.username
    return JSONResponse({"message": "Login successful"})


@app.get("/balance")
def get_balance(username: str, token: str):
    return balances.get(username, {}).get(token, 0)


@app.get("/orders")
def get_orders():
    return [w.order for w in order_book_wrapped]


@app.post("/order")
def place_order(order: OrderRequest, request: Request):
    user = request.session.get("username")
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    user_bal = balances.get(user, {})
    cost = order.quantity * order.price

    if order.order_type == "buy":
        if user_bal.get(order.quote_token, 0.0) < cost:
            raise HTTPException(
                status_code=403, detail="Insufficient quote token balance"
            )
        user_bal[order.quote_token] -= cost
    elif order.order_type == "sell":
        if user_bal.get(order.base_token, 0.0) < order.quantity:
            raise HTTPException(
                status_code=403, detail="Insufficient base token balance"
            )
        user_bal[order.base_token] -= order.quantity
    else:
        raise HTTPException(status_code=400, detail="Invalid order type")

    new_order = {
        "id": str(uuid4()),
        "user": user,
        "base_token": order.base_token,
        "quote_token": order.quote_token,
        "order_type": order.order_type,
        "quantity": order.quantity,
        "price": order.price,
    }

    match_order(new_order)

    # Only insert unmatched portion of the order
    if new_order["quantity"] > 0:
        sort_price = (
            -new_order["price"]
            if new_order["order_type"] == "buy"
            else new_order["price"]
        )
        wrapped = OrderWrapper(sort_index=sort_price, order=new_order)
        insort(order_book_wrapped, wrapped)

    return {"message": "Order placed", "order_id": new_order["id"]}


# Matching engine
def match_order(new_order: dict):
    i = 0
    while i < len(order_book_wrapped):
        existing = order_book_wrapped[i].order

        # Skip if the order is not compatible for matching
        if (
            existing["user"] == new_order["user"]
            or existing["base_token"] != new_order["base_token"]
            or existing["quote_token"] != new_order["quote_token"]
            or existing["order_type"] == new_order["order_type"]
        ):
            i += 1
            continue

        # Check if price matches
        price_ok = (
            new_order["order_type"] == "buy" and existing["price"] <= new_order["price"]
        ) or (
            new_order["order_type"] == "sell"
            and existing["price"] >= new_order["price"]
        )

        if not price_ok:
            i += 1
            continue

        # Perform the trade
        trade_qty = min(new_order["quantity"], existing["quantity"])
        new_order["quantity"] -= trade_qty
        existing["quantity"] -= trade_qty
        update_balances(new_order, existing, trade_qty)

        # Remove matched order if it's fully filled
        if existing["quantity"] == 0:
            order_book_wrapped.pop(i)
        else:
            i += 1

        # Stop if the new order is fully filled
        if new_order["quantity"] == 0:
            break


# Balance update
def update_balances(order1: dict, order2: dict, qty: float):
    buyer = order1 if order1["order_type"] == "buy" else order2
    seller = order2 if order1["order_type"] == "buy" else order1

    quote_token = buyer["quote_token"]
    base_token = buyer["base_token"]
    total_price = qty * buyer["price"]

    balances[buyer["user"]][base_token] = (
        balances[buyer["user"]].get(base_token, 0.0) + qty
    )
    balances[seller["user"]][quote_token] = (
        balances[seller["user"]].get(quote_token, 0.0) + total_price
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, port=5001)
