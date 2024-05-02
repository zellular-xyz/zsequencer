from flask import Flask, request, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///orders.db'
app.config['SECRET_KEY'] = 'your_secret_key'
db = SQLAlchemy(app)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)

class Balance(db.Model):
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    token = db.Column(db.String(50), primary_key=True)
    amount = db.Column(db.Float, nullable=False)

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    base_token = db.Column(db.String(50), nullable=False)
    quote_token = db.Column(db.String(50), nullable=False)
    order_type = db.Column(db.String(10), nullable=False)  # 'buy' or 'sell'
    quantity = db.Column(db.Float, nullable=False)  # quantity of base token
    price = db.Column(db.Float, nullable=False)  # price in quote tokens per base token
    matched = db.Column(db.Boolean, default=False, nullable=False)

@app.before_first_request
def create_tables():
    db.create_all()

@app.route('/login', methods=['POST'])
def login():
    username = request.form['username']
    password = request.form['password']
    user = User.query.filter_by(username=username).first()
    if user and check_password_hash(user.password_hash, password):
        session['user_id'] = user.id
        return jsonify({"message": "Logged in successfully"}), 200
    return jsonify({"message": "Invalid username or password"}), 401

@app.route('/order', methods=['POST'])
def place_order():
    if 'user_id' not in session:
        return jsonify({"message": "Please log in"}), 401

    order_type = request.form['order_type']
    base_token = request.form['base_token']
    quote_token = request.form['quote_token']
    quantity = float(request.form['quantity'])
    price = float(request.form['price'])

    # Determine the cost in quote tokens and check balances
    cost_in_quote = quantity * price

    quote_balance = Balance.query.filter_by(user_id=session['user_id'], token=quote_token).first()
    base_balance = Balance.query.filter_by(user_id=session['user_id'], token=base_token).first()

    if order_type == 'buy':
        if not quote_balance or quote_balance.amount < cost_in_quote:
            return jsonify({"message": "Insufficient quote token balance"}), 403
        quote_balance.amount -= cost_in_quote
    elif order_type == 'sell':
        if not base_balance or base_balance.amount < quantity:
            return jsonify({"message": "Insufficient base token balance"}), 403
        base_balance.amount -= quantity

    new_order = Order(user_id=session['user_id'], order_type=order_type, base_token=base_token, quote_token=quote_token, quantity=quantity, price=price)
    db.session.add(new_order)
    db.session.flush()  # Allows us to use the id of the new_order before committing
    matched = match_order(new_order)
    if not matched:
        db.session.commit()
    return jsonify({"message": "Order placed"}), 201

def match_order(new_order):
    # Logic to find and process matching orders
    matched_orders = Order.query.filter(
        Order.base_token == new_order.base_token,
        Order.quote_token == new_order.quote_token,
        Order.order_type != new_order.order_type,
        Order.price <= new_order.price if new_order.order_type == 'buy' else Order.price >= new_order.price
    ).order_by(Order.price.asc() if new_order.order_type == 'buy' else Order.price.desc()).all()

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
    buyer = new_order if new_order.order_type == 'buy' else matched_order
    seller = matched_order if new_order.order_type == 'buy' else new_order
    buyer_quote_balance = Balance.query.filter_by(user_id=buyer.user_id, token=buyer.quote_token).first()
    seller_base_balance = Balance.query.filter_by(user_id=seller.user_id, token=seller.base_token).first()

    # Buyer pays in quote tokens
    buyer_quote_balance.amount -= trade_quantity * new_order.price
    seller_base_balance.amount += trade_quantity

    # Seller receives quote tokens
    seller_quote_balance = Balance.query.filter_by(user_id=seller.user_id, token=seller.quote_token).first()
    buyer_base_balance = Balance.query.filter_by(user_id=buyer.user_id, token=buyer.base_token).first()
    seller_quote_balance.amount += trade_quantity * new_order.price
    buyer_base_balance.amount += trade_quantity

    db.session.commit()

if __name__ == '__main__':
    app.run(debug=True)