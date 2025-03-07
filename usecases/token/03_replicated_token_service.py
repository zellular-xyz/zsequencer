import logging
import json
from threading import Thread
from zellular import Zellular
from flask import Flask, request, jsonify
from eth_account import Account
from eth_account.messages import encode_defunct

app = Flask(__name__)
app.config["SECRET_KEY"] = "supersecretkey"

balances = {"0xc66F8Fba940064B5bA8d437d6fF829E60134230E": 100}

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app_name = "token"
node_url = "http://5.161.230.186:6001"
zellular = Zellular(app_name, node_url, threshold_percent=1)

def verify_signature(sender, message, signature):
    message_hash = encode_defunct(text=message)
    recovered_address = Account.recover_message(message_hash, signature=signature)
    return recovered_address.lower() == sender.lower()


@app.route("/transfer", methods=["POST"])
def transfer():
    data = request.json
    sender, receiver, amount, signature = (
        data["sender"], data["receiver"], data["amount"], data["signature"]
    )

    message = f"Transfer {amount} to {receiver}"
    if not verify_signature(sender, message, signature):
        return jsonify({"error": "Invalid signature"}), 401

    if balances.get(sender, 0) < amount:
        return jsonify({"error": "Insufficient balance"}), 400

    txs = [{
        "sender": sender,
        "receiver": receiver,
        "amount": amount,
        "signature": signature
    }]

    zellular.send(txs, blocking=False)
    return jsonify({"message": "Transfer sent"})


def __transfer(data):
    sender, receiver, amount, signature = (
        data["sender"], data["receiver"], data["amount"], data["signature"]
    )

    message = f"Transfer {amount} to {receiver}"
    if not verify_signature(sender, message, signature):
        return logger.error(f"Invalid signature: {data}")

    if balances.get(sender, 0) < amount:
        return logger.error(f"Insufficient balance: {data}")

    balances[sender] -= amount
    balances[receiver] = balances.get(receiver, 0) + amount
    return logger.info(f"Transfer successful: {data} ")


@app.route("/balance", methods=["GET"])
def balance():
    address = request.args.get("address")
    key_pair = new_key_pair_from_string("a1b2c3d4")
    message = b"Hello, world!"
    return jsonify({"address": address, "balance": balances.get(address, 0)})


def process_loop():
    for batch, index in zellular.batches():
        txs = json.loads(batch)
        for i, tx in enumerate(txs):
            __transfer(tx)


if __name__ == "__main__":
    Thread(target=process_loop).start()
    app.run(debug=False, port=5001)

