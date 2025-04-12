from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from ecdsa import VerifyingKey, SECP256k1, BadSignatureError
import base64
import requests
from threading import Thread
import time

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///orders.db"
app.config["SECRET_KEY"] = "your_secret_key"
db = SQLAlchemy(app)
zsequencer_url = "http://localhost:8323/node/transactions"


class Balance(db.Model):
    public_key = db.Column(db.String(500), primary_key=True)
    token = db.Column(db.String(50), primary_key=True)
    amount = db.Column(db.Float, nullable=False)


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    public_key = db.Column(db.String(500), nullable=False)
    base_token = db.Column(db.String(50), nullable=False)
    quote_token = db.Column(db.String(50), nullable=False)
    order_type = db.Column(db.String(10), nullable=False)  # 'buy' or 'sell'
    quantity = db.Column(db.Float, nullable=False)  # quantity of base token
    price = db.Column(db.Float, nullable=False)  # price in quote tokens per base token
    matched = db.Column(db.Boolean, default=False, nullable=False)


@app.before_first_request
def create_tables():
    db.create_all()


def verify_order(order):
    # Serialize the data from the form fields
    keys = ["order_type", "base_token", "quote_token", "quantity", "price"]
    message = ",".join([order[key] for key in keys]).encode("utf-8")

    # Verify the signature
    try:
        public_key = base64.b64decode(order["public_key"])
        signature = base64.b64decode(order["signature"])
        vk = VerifyingKey.from_string(public_key, curve=SECP256k1)
        vk.verify(signature, message)
    except (BadSignatureError, ValueError):
        return False
    return True


@app.route("/order", methods=["POST"])
def place_order():
    if not verify_order(request.form):
        return jsonify({"message": "Invalid signature"}), 403

    keys = ["order_type", "base_token", "quote_token", "quantity", "price"]
    headers = {"Content-Type": "application/json"}
    data = {
        "transactions": [{key: request.form[key] for key in keys}],
        "timestamp": int(time.time()),
    }
    requests.put(zsequencer_url, jsonify(data), headers=headers)
    return {"success": True}


def process_loop():
    last = 0
    while True:
        params = {"after": last, "states": ["finalized"]}
        response = requests.get(zsequencer_url, params=params)
        finalized_txs = response.json().get("data")
        if not finalized_txs:
            time.sleep(1)
            continue

        last = max(tx["index"] for tx in finalized_txs)
        sorted_numbers = sorted([t["index"] for t in finalized_txs])
        print(
            f"\nreceive finalized indexes: [{sorted_numbers[0]}, ..., {sorted_numbers[-1]}]",
        )
        for tx in finalized_txs:
            place_order(tx)


def __place_order(order):
    if not verify_order(order):
        print("Invalid signature:", order)
        return

    order_type = order["order_type"]
    base_token = order["base_token"]
    quote_token = order["quote_token"]
    quantity = float(order["quantity"])
    price = float(order["price"])

    # Determine the cost in quote tokens and check balances
    cost_in_quote = quantity * price

    quote_balance = Balance.query.filter_by(
        user_id=session["user_id"], token=quote_token
    ).first()
    base_balance = Balance.query.filter_by(
        user_id=session["user_id"], token=base_token
    ).first()

    if order_type == "buy":
        if not quote_balance or quote_balance.amount < cost_in_quote:
            return jsonify({"message": "Insufficient quote token balance"}), 403
        quote_balance.amount -= cost_in_quote
    elif order_type == "sell":
        if not base_balance or base_balance.amount < quantity:
            return jsonify({"message": "Insufficient base token balance"}), 403
        base_balance.amount -= quantity

    new_order = Order(
        user_id=session["user_id"],
        order_type=order_type,
        base_token=base_token,
        quote_token=quote_token,
        quantity=quantity,
        price=price,
    )
    db.session.add(new_order)
    db.session.flush()  # Allows us to use the id of the new_order before committing
    matched = match_order(new_order)
    if not matched:
        db.session.commit()
    return jsonify({"message": "Order placed"}), 201


def match_order(new_order):
    # Logic to find and process matching orders
    matched_orders = (
        Order.query.filter(
            Order.base_token == new_order.base_token,
            Order.quote_token == new_order.quote_token,
            Order.order_type != new_order.order_type,
            Order.price <= new_order.price
            if new_order.order_type == "buy"
            else Order.price >= new_order.price,
        )
        .order_by(
            Order.price.asc() if new_order.order_type == "buy" else Order.price.desc()
        )
        .all()
    )

    for matched_order in matched_orders:
        if new_order.quantity == 0:
            break

        trade_quantity = min(new_order.quantity, matched_order.quantity)

        # Update quantities
        new_order.quantity -= trade_quantity
        matched_order.quantity -= trade_quantity

        # Update balances for base and quote tokens
        update_balances(new_order, matched_order, trade_quantity)

        if matched_order.quantity == 0:
            matched_order.matched = True
        db.session.commit()

    if new_order.quantity == 0:
        new_order.matched = True
        db.session.commit()
    return new_order.matched


def update_balances(new_order, matched_order, trade_quantity):
    # Logic to update balances after matching orders
    buyer = new_order if new_order.order_type == "buy" else matched_order
    seller = matched_order if new_order.order_type == "buy" else new_order
    buyer_quote_balance = Balance.query.filter_by(
        user_id=buyer.user_id, token=buyer.quote_token
    ).first()
    seller_base_balance = Balance.query.filter_by(
        user_id=seller.user_id, token=seller.base_token
    ).first()

    # Buyer pays in quote tokens
    buyer_quote_balance.amount -= trade_quantity * new_order.price
    seller_base_balance.amount += trade_quantity

    # Seller receives quote tokens
    seller_quote_balance = Balance.query.filter_by(
        user_id=seller.user_id, token=seller.quote_token
    ).first()
    buyer_base_balance = Balance.query.filter_by(
        user_id=buyer.user_id, token=buyer.base_token
    ).first()
    seller_quote_balance.amount += trade_quantity * new_order.price
    buyer_base_balance.amount += trade_quantity

    db.session.commit()


if __name__ == "__main__":
    Thread(target=process_loop).start()
    app.run(debug=True)
