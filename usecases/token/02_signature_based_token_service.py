from flask import Flask, request, jsonify
from eth_account import Account
from eth_account.messages import encode_defunct

app = Flask(__name__)
app.config["SECRET_KEY"] = "supersecretkey"

# List addresses with initial balances
balances = {"0xc66F8Fba940064B5bA8d437d6fF829E60134230E": 100}

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

    balances[sender] -= amount
    balances[receiver] = balances.get(receiver, 0) + amount
    return jsonify({"message": "Transfer successful"})


@app.route("/balance", methods=["GET"])
def balance():
    address = request.args.get("address")
    return jsonify({"address": address, "balance": balances.get(address, 0)})


if __name__ == "__main__":
    app.run(debug=True, port=5001)

