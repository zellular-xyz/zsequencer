import requests
from eth_account import Account
from eth_account.messages import encode_defunct

# The private key for "0xc66F8Fba940064B5bA8d437d6fF829E60134230E" with initial balance of 100
SENDER_PRIVATE_KEY = "0x4b7f4de058ab4d3629f438c1728ac77bea7f4ab0099218be77242f8ba099cca7"
SENDER_ADDRESS = Account.from_key(SENDER_PRIVATE_KEY).address
RECEIVER_ADDRESS = "0x2B3e5649A2Bfc3667b1db1A0ae7E1f9368d676A9"
AMOUNT = 10
TOKEN_SERVICE_NODE_URL = "http://127.0.0.1:5001"

# -- start: signing transfer --
message = f"Transfer {AMOUNT} to {RECEIVER_ADDRESS}"
message_hash = encode_defunct(text=message)
signed_message = Account.sign_message(message_hash, private_key=SENDER_PRIVATE_KEY)
signature = signed_message.signature.hex()
# -- end: signing transfer --

payload = {
    "sender": SENDER_ADDRESS,
    "receiver": RECEIVER_ADDRESS,
    "amount": AMOUNT,
    "signature": signature
}
response = requests.post(f"{TOKEN_SERVICE_NODE_URL}/transfer", json=payload)
print(response.json())
