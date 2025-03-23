import httpx
from eth_account import Account
from eth_account.messages import encode_defunct

BASE_URL = "http://localhost:8000"

# === Simulated user private keys ===
user1_key = "0x4b7f4de058ab4d3629f438c1728ac77bea7f4ab0099218be77242f8ba099cca7"
user2_key = "0x28a3947aa36917ca22f56765c67bedc2fdbbd2daf73f8a2cdb1c0dd252cefc3c"

user1_account = Account.from_key(user1_key)
user2_account = Account.from_key(user2_key)

# === Orders ===
buy_order = {
    "order_type": "buy",
    "base_token": "ETH",
    "quote_token": "USDT",
    "quantity": 1.0,
    "price": 200.0
}

sell_order = {
    "order_type": "sell",
    "base_token": "ETH",
    "quote_token": "USDT",
    "quantity": 1.0,
    "price": 200.0
}

def sign_order(account: Account, order: dict) -> dict:
    message = f"Order {order['order_type']} {order['quantity']} {order['base_token']} at {order['price']} {order['quote_token']}"
    message_hash = encode_defunct(text=message)
    signed = Account.sign_message(message_hash, private_key=account.key)

    signed_order = {
        "sender": account.address,
        **order,
        "signature": signed.signature.hex()
    }
    return signed_order

def place_order(order_data):
    with httpx.Client() as client:
        response = client.post(f"{BASE_URL}/order", json=order_data)
        print(f"Placed {order_data['order_type']} order from {order_data['sender']}")
        print("Response:", response.json())

# === Send orders ===
if __name__ == "__main__":
    buy_payload = sign_order(user1_account, buy_order)
    sell_payload = sign_order(user2_account, sell_order)

    place_order(buy_payload)
    place_order(sell_payload)
