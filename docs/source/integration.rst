Integration Guide
=================

To illustrate how apps can be decentralized with the Zellular Sequencer, let's look at a basic order book created using Python with Flask for handling user orders and SQLite for data storage. This example is streamlined, focusing solely on demonstrating the practical integration with the Zellular Sequencer, and does not include the extensive features of a full-scale implementation.

Python Code for a Simple Order-Book
-----------------------------------

The complete code for the sample order book is available at `this link <https://github.com/zelluar_xy/zsequencer/blob/18ba23dda29813820d658c5033ad945784f88b31/docs/codes/order_book.py>`_. Below is a brief overview of the code structure:

Setting up the Environment
~~~~~~~~~~~~~~~~~~~~~~~~~~

This section sets up the basic Flask application and the database:

.. code-block:: python

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
        order_type = db.Column(db.String(10), nullable=False)
        quantity = db.Column(db.Float, nullable=False)
        price = db.Column(db.Float, nullable=False)
        matched = db.Column(db.Boolean, default=False, nullable=False)

    @app.before_first_request
    def create_tables():
        db.create_all()

User Authentication
~~~~~~~~~~~~~~~~~~~

This section adds a login route to authenticate users:

.. code-block:: python

    @app.route('/login', methods=['POST'])
    def login():
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            return jsonify({"message": "Logged in successfully"}), 200
        return jsonify({"message": "Invalid username or password"}), 401

Order Submission
~~~~~~~~~~~~~~~~

:code:`place_order` adds a route to the server to enable users submitting buy and sell orders if they have logged in and have a session:

.. code-block:: python

    @app.route('/order', methods=['POST'])
    def place_order():
        if 'user_id' not in session:
            return jsonify({"message": "Please log in"}), 401

        order_type = request.form['order_type']
        base_token = request.form['base_token']
        quote_token = request.form['quote_token']
        quantity = float(request.form['quantity'])
        price = float(request.form['price'])

        ...


Order Matching
~~~~~~~~~~~~~~

:code:`match_order` and :code:`update_balances` implement the core logic of matching orders and updating users balances:

.. code-block:: python

    def match_order(new_order):
        # Logic to find and process matching orders
        ...


    def update_balances(new_order, matched_order, trade_quantity):
        # Logic to update balances after matching orders
        ...


Applying Signature-based Authentication
---------------------------------------

To decentralize an app like the order-book using the Zellular Sequencer, start by switching to a signature-based authentication system. Here’s how to do it:

Identifying Users by their Public Keys
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Since username and password are no longer needed for authentication, the :code:`User` table can be eliminated. Additionally, update the :code:`user_id` field in the :code:`Order` and :code:`Balance` table to reference the user's :code:`public_key`, which serves as the user identifier in the new version.

.. code-block:: python

    class Balance(db.Model):
        public_key = db.Column(db.String(500), primary_key=True)
        ...

    class Order(db.Model):
        ...
        public_key = db.Column(db.String(500), nullable=False)
        ...

Authorising Users by their Signatures
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Remove the login function, as session-based authentication is no longer used, and users sign every request. Add a signature parameter to the :code:`place_order` function, using this signature to verify access authorization instead of relying on user sessions.

.. code-block:: python

    from ecdsa import VerifyingKey, SECP256k1, BadSignatureError
    ...

    def verify_order(order):
        # Serialize the data from the form fields
        keys = ['order_type', 'base_token', 'quote_token', 'quantity', 'price']
        message = ','.join([order[key] for key in keys]).encode('utf-8')

        # Verify the signature
        try:
            public_key = base64.b64decode(order['public_key'])
            signature = base64.b64decode(order['signature'])
            vk = VerifyingKey.from_string(public_key, curve=SECP256k1)
            vk.verify(signature, message)
        except (BadSignatureError, ValueError):
            return False
        return True

    @app.route('/order', methods=['POST'])
    def place_order():
        if not verify_order(request.form):
            return jsonify({"message": "Invalid signature"}), 403

        ...

Sequencing orders before applying them
---------------------------------------

The next step in decentralizing the app is to send user-signed orders to the Zellular Sequencer before applying them to the database and update the database after receiving them back from the sequencer. This helps all the nodes running the app apply the requests in a consistent order. Here’s how it should be done:

Sending orders to the Sequencer
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

After signature verification, the place_order function uses the :code:`POST /node/{app}/batches` endpoint of the Zellular Sequencer service to send the orders to the sequencer before applying them into the database.


.. code-block:: python

    zsequencer_url = 'http://5.161.230.186:6001/node/orderbook/batches'
    ...

    @app.route('/order', methods=['POST'])
    def place_order():
        if not verify_order(request.form):
            return jsonify({"message": "Invalid signature"}), 403

        keys = ['order_type', 'base_token', 'quote_token', 'quantity', 'price', 'signature']
        txs = [{key: request.form[key] for key in keys}]
        requests.put(zsequencer_url, json=txs)
        return { 'success': True }

Receiving sequenced orders from the sequencer
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Add a thread to continuously retrieve finalized, sequenced orders and apply the same routine used in the :code:`place_order` function to process these orders. `Zellular SDK <https://github.com/zellular-xyz/zellular.py>`_ can be used to pull the finalized sequence of transaction batches from the Zellular network.


.. code-block:: python

    import zellular

    def process_loop():
        verifier = zellular.Verifier("orderbook", "http://5.161.230.186:6001")
        for batch, index in verifier.batches():
            txs = json.loads(batch)
            for i, tx in enumerate(txs):
                place_order(tx)

    def __place_order(order):
        if not verify_order(order):
            print("Invalid signature:", order)
            return
        ...

    if __name__ == '__main__':
        Thread(target=process_loop).start()
        app.run(debug=True)

The complete code for the decentralized version of the sample order book can be accessed `here <https://github.com/zellular-xyz/zsequencer/blob/main/docs/codes/order_book.py>`_. Additionally, you can view the GitHub comparison between the centralized and decentralized versions `here <https://github.com/zellular-xyz/zsequencer/compare/18ba23d..39a1a42>`_. As demonstrated, integrating the Zellular Sequencer into your apps is straightforward and accessible for any Python developer, without requiring deep expertise in blockchain or smart contracts.