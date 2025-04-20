import json
import logging
from bisect import insort
from dataclasses import dataclass, field
from threading import Thread
from typing import Any
from uuid import uuid4

from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from zellular import Zellular

app = FastAPI()
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Zellular setup
zellular = Zellular("orderbook", "http://37.27.41.237:6001/", threshold_percent=1)

# In-memory balances
balances: dict[str, dict[str, float]] = {
    "0xc66F8Fba940064B5bA8d437d6fF829E60134230E": {"USDT": 1000.0},
    "0x7F3b0b1530A0d0Ce3D721a6e976C7eA4296A0f5d": {"ETH": 5.0},
}


@dataclass(order=True)
class OrderWrapper:
    sort_index: float
    order: dict = field(compare=False)


# Order book
order_book_wrapped: list[OrderWrapper] = []


# Order request schema
class OrderRequest(BaseModel):
    sender: str
    order_type: str  # 'buy' or 'sell'
    base_token: str
    quote_token: str
    quantity: float
    price: float
    signature: str


# --- Routes ---


@app.get("/balance")
def get_balance(address: str, token: str):
    return balances.get(address, {}).get(token, 0)


@app.get("/orders")
def get_orders():
    return [w.order for w in order_book_wrapped]


# -- start: submitting order to zellular --
@app.post("/order")
def place_order(order: OrderRequest):
    message = f"Order {order.order_type} {order.quantity} {order.base_token} at {order.price} {order.quote_token}"
    if not verify_signature(order.sender, message, order.signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    order_payload = {
        "id": str(uuid4()),
        "user": order.sender,
        "order_type": order.order_type,
        "base_token": order.base_token,
        "quote_token": order.quote_token,
        "quantity": order.quantity,
        "price": order.price,
        "signature": order.signature,
    }

    # Send to Zellular for consensus-based processing
    zellular.send([order_payload], blocking=False)
    return JSONResponse({"message": "Order sent to consensus layer"})


# -- end: submitting order to zellular --


# Core order processing
def apply_order(order: dict[str, Any]) -> None:
    user = order["user"]
    order_type = order["order_type"]
    base_token = order["base_token"]
    quote_token = order["quote_token"]
    quantity = order["quantity"]
    price = order["price"]
    signature = order["signature"]

    message = f"Order {order_type} {quantity} {base_token} at {price} {quote_token}"
    if not verify_signature(user, message, signature):
        logger.error(f"Invalid signature in replicated order: {order}")
        return

    user_bal = balances.get(user, {})
    cost = quantity * price

    if order_type == "buy":
        if user_bal.get(quote_token, 0.0) < cost:
            logger.error(f"Insufficient balance for {user}")
            return
        user_bal[quote_token] -= cost
    elif order_type == "sell":
        if user_bal.get(base_token, 0.0) < quantity:
            logger.error(f"Insufficient balance for {user}")
            return
        user_bal[base_token] -= quantity
    else:
        logger.error(f"Invalid order type: {order_type}")
        return

    new_order = {
        "id": order["id"],
        "user": user,
        "base_token": base_token,
        "quote_token": quote_token,
        "order_type": order_type,
        "quantity": quantity,
        "price": price,
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

    logger.info(f"Order placed: {new_order}")


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


# Signature verification
def verify_signature(sender: str, message: str, signature: str) -> bool:
    try:
        message_hash = encode_defunct(text=message)
        recovered = Account.recover_message(message_hash, signature=signature)
        return recovered.lower() == sender.lower()
    except Exception:
        return False


# Zellular replication loop
# -- start: processing loop --
def process_loop():
    for batch, index in zellular.batches():
        try:
            txs = json.loads(batch)
            for tx in txs:
                apply_order(tx)
        except Exception as e:
            logger.error(f"Error processing batch #{index}: {e}")


# -- end: processing loop --

if __name__ == "__main__":
    Thread(target=process_loop, daemon=True).start()
    import uvicorn

    uvicorn.run(app, port=5001)
