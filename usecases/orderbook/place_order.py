import httpx

BASE_URL = "http://localhost:8000"

user1 = {"username": "user1", "password": "pass1"}
user2 = {"username": "user2", "password": "pass2"}

buy_order = {
    "order_type": "buy",
    "base_token": "ETH",
    "quote_token": "USDT",
    "quantity": 1,
    "price": 200
}

sell_order = {
    "order_type": "sell",
    "base_token": "ETH",
    "quote_token": "USDT",
    "quantity": 1,
    "price": 200
}

def place_order(client, order):
    response = client.post(f"{BASE_URL}/order", json=order)
    print("Order response:", response.json())

with httpx.Client(follow_redirects=True) as client1, httpx.Client(follow_redirects=True) as client2:
    # Log in user1
    r1 = client1.post(f"{BASE_URL}/login", json=user1)
    print("User1 login:", r1.json())

    # Place buy order as user1
    place_order(client1, buy_order)

    # Log in user2
    r2 = client2.post(f"{BASE_URL}/login", json=user2)
    print("User2 login:", r2.json())

    # Place sell order as user2
    place_order(client2, sell_order)
