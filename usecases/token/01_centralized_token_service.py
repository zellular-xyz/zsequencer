from flask import Flask, request, jsonify, session
from flask_session import Session

app = Flask(__name__)
app.config["SECRET_KEY"] = "supersecretkey"
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

users = {"user1": "pass1"}
balances = {"user1": 100}


@app.route("/login", methods=["POST"])
def login():
    data = request.json
    if users.get(data["username"]) != data["password"]:
        return jsonify({"error": "Invalid credentials"}), 401
    session["username"] = data["username"]
    return jsonify({"message": "Login successful"})


@app.route("/transfer", methods=["POST"])
def transfer():
    if "username" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json
    sender, receiver, amount = (
        session["username"], data["receiver"], data["amount"]
    )

    if balances.get(sender, 0) < amount:
        return jsonify({"error": "Insufficient balance"}), 400

    balances[sender] -= amount
    balances[receiver] = balances.get(receiver, 0) + amount
    return jsonify({"message": "Transfer successful"})


@app.route("/balance", methods=["GET"])
def balance():
    username = request.args.get("username")
    return jsonify({"username": username, "balance": balances.get(username, 0)})


if __name__ == "__main__":
    app.run(debug=True, port=5001)
