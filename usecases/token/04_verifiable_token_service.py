import logging
import json
from threading import Thread
from zellular import Zellular
from flask import Flask, request, jsonify
from eth_account import Account
from eth_account.messages import encode_defunct
from blspy import PopSchemeMPL, PrivateKey

app = Flask(__name__)
app.config["SECRET_KEY"] = "supersecretkey"

# Uncomment 2nd/3rd private keys and ports for running 2nd/3rd nodes

# NODE_PRIVATE_KEY, PORT = '5b009195821da22cf90f375db7ee2dcf698791a5190a0b50dda3af653ee67d9b', 5001
NODE_PRIVATE_KEY, PORT = '53217fdb58315338ab035f6939b9c684ca54ec7fa7da2f78cf9583af5799fb40', 5002
# NODE_PRIVATE_KEY, PORT = '7126ea0f6c7acb39d30ce7fde262a8a1fc53f5d994ef03be265d65bf370ad184', 5003

sk = PrivateKey.from_bytes(bytes.fromhex(NODE_PRIVATE_KEY))

balances = {"0xc66F8Fba940064B5bA8d437d6fF829E60134230E": 100}

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

zellular = Zellular("token", "http://37.27.41.237:6001/", threshold_percent=1)

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
    balance = balances.get(address, 0)
    message = f"Address: {address}, Balance: {balance}".encode('utf-8')
    signature = PopSchemeMPL.sign(sk, message)
    return jsonify({"address": address, "balance": balance, "signature": str(signature)})


def process_loop():
    for batch, index in zellular.batches():
        txs = json.loads(batch)
        for i, tx in enumerate(txs):
            __transfer(tx)


if __name__ == "__main__":
    Thread(target=process_loop).start()
    app.run(debug=False, port=PORT)

