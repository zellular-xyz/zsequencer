Orderbook as a Verifiable Service
=================================

This guide walks through transforming a simple centralized orderbook into a fully decentralized and verifiable service using the Zellular Sequencer.

We follow a progressive enhancement model, starting from a basic session-based FastAPI service, and incrementally evolving it into a replicated and cryptographically verifiable system.

Each step corresponds to a real implementation in the Zellular :src:`orderbook` directory.

Step 1: Centralized Orderbook Service
-------------------------------------

In this stage, we implement a basic in-memory orderbook service using FastAPI and session-based authentication. Users log in with a username and password, and can place buy/sell orders if they have sufficient balance. Submitted orders are either matched immediately or added to the orderbook.

📄 File: :src:`orderbook/01_centralized_orderbook_service.py`

Key Concepts
~~~~~~~~~~~~

- Session-based login using `SessionMiddleware`
- In-memory user balances per token (e.g., USDT, ETH)
- Buy/sell order schema with immediate price-based matching
- Orders are stored using `OrderWrapper` and sorted by price
- Partially filled or unmatched orders are added to the book

Endpoints
~~~~~~~~~

- `POST /login`: Log in with a username and password
- `GET /balance`: Check a user's token balance
- `GET /orders`: Retrieve all open orders
- `POST /order`: Submit a new buy or sell order

Order Schema
~~~~~~~~~~~~

Orders are submitted in the following format:

.. code-block:: json

   {
     "order_type": "buy",          // or "sell"
     "base_token": "ETH",
     "quote_token": "USDT",
     "quantity": 1.5,
     "price": 2000.0
   }

Only authenticated users can place orders.

Order Matching Logic
~~~~~~~~~~~~~~~~~~~~

When an order is submitted:

- The service checks that the user has sufficient balance:
  - For **buy**: `quote_token ≥ price × quantity`
  - For **sell**: `base_token ≥ quantity`
- The order is passed to the `match()` function:
  - **Buy orders** match with the lowest-priced sell orders
  - **Sell orders** match with the highest-priced buy orders
- Trades update both users' balances (quote and base tokens)
- If the order is only partially filled, the remainder is added to the book

The orderbook is maintained using Python’s `bisect.insort` for efficient price-based sorting.

Example Usage
~~~~~~~~~~~~~

1. **Login**

.. code-block:: bash

   curl -X POST http://localhost:5001/login \
        -H "Content-Type: application/json" \
        -d '{"username": "user1", "password": "pass1"}' \
        -c cookies.txt

2. **Place an order**

.. code-block:: bash

   curl -X POST http://localhost:5001/order \
        -H "Content-Type: application/json" \
        -d '{
              "order_type": "buy",
              "base_token": "ETH",
              "quote_token": "USDT",
              "quantity": 1,
              "price": 2000
            }' \
        -b cookies.txt

3. **View all open orders**

.. code-block:: bash

   curl http://localhost:5001/orders

Testing with Script
~~~~~~~~~~~~~~~~~~~

A helper script is provided for testing this centralized version of the orderbook:

📄 File: :src:`orderbook/01_place_order.py`

This script:

- Logs in with a username/password
- Submits a sample order using the session cookie
- Prints the server response

To run it:

.. code-block:: bash

   python examples/orderbook/01_place_order.py

Limitations
~~~~~~~~~~~

- Order matching is basic and does not use time-priority
- State (balances and orderbook) is stored in-memory only
- No cryptographic authentication or verifiability
- Service is centralized and not fault-tolerant

Next, we’ll remove session-based login and introduce **signature-based authentication** using Ethereum-style keys.

Step 2: Signature-Based Orderbook Service
-----------------------------------------

In this step, we remove session-based login and introduce **stateless authentication using Ethereum-style signatures**. Users now sign order messages off-chain using their wallet's private key. The backend verifies the signature and uses the recovered address as the sender.

📄 File: :src:`orderbook/02_signature_based_orderbook_service.py`

Key Concepts
~~~~~~~~~~~~

- Stateless authentication using ECDSA signatures
- Each order includes a signed message
- The backend verifies the signature and derives the sender
- Orders are matched immediately upon submission

Message Format for Signing
~~~~~~~~~~~~~~~~~~~~~~~~~~

Users must sign the following message string off-chain:

.. code-block:: text

   Order {order_type} {quantity} {base_token} at {price} {quote_token}

Example:

.. code-block:: text

   Order buy 1.5 ETH at 2000 USDT

Backend Verification
~~~~~~~~~~~~~~~~~~~~

The server reconstructs the message and verifies the signature:


.. literalinclude:: ../../../examples/orderbook/02_signature_based_orderbook_service.py
   :language: python
   :lines: 142-148


.. literalinclude:: ../../../examples/orderbook/02_signature_based_orderbook_service.py
   :language: python
   :lines: 27-34

.. literalinclude:: ../../../examples/orderbook/02_signature_based_orderbook_service.py
   :language: python
   :lines: 46-50


Testing with Script
~~~~~~~~~~~~~~~~~~~

📄 File: :src:`orderbook/02_place_order.py`

This script:

- Signs an order off-chain using a private key
- Sends it to the `/order` endpoint
- Demonstrates stateless interaction using a wallet-like client

Run it with:

.. code-block:: bash

   python examples/orderbook/02_place_order.py

Why This Matters
~~~~~~~~~~~~~~~~

- The service no longer requires login or session state
- Any node can independently verify the sender of an order
- Clients and servers interact in a stateless, cryptographically secure way
- This lays the foundation for distributed, multi-node replication

Next, we’ll replicate the orderbook across nodes using the **Zellular Sequencer** to ensure all participants observe the same transaction order.

Step 3: Replicated Orderbook Service
------------------------------------

In this step, we replicate the orderbook across a network of nodes using the **Zellular Sequencer**. Instead of applying new orders immediately upon submission, each order is sent to the sequencer, which assigns it a global order and broadcasts it to all replicas.

Each node independently pulls the ordered sequence of operations and applies them locally, ensuring that the **orderbook and balances remain consistent** across all nodes.

📄 File: :src:`orderbook/03_replicated_orderbook_service.py`

Key Concepts
~~~~~~~~~~~~

- Orders are sent to the Zellular Sequencer via the SDK
- All nodes fetch and apply the same ordered batch of operations
- Order matching logic is executed identically on every node
- Ensures deterministic and consistent state replication

Order Submission
~~~~~~~~~~~~~~~~

Orders are received at the `/order` endpoint. After signature verification and basic balance check, they are submitted to the sequencer:

.. literalinclude:: ../../../examples/orderbook/03_replicated_orderbook_service.py
   :language: python
   :lines: 56-75

This means the order will be processed once it appears in a sequenced batch.

Order Processing Loop
~~~~~~~~~~~~~~~~~~~~~

Each node runs a background thread to pull and apply new batches from Zellular:


.. literalinclude:: ../../../examples/orderbook/03_replicated_orderbook_service.py
   :language: python
   :lines: 194-201

This ensures that all replicas receive and apply the same operations in the same order.

Why This Matters
~~~~~~~~~~~~~~~~

- Introduces true multi-node replication
- Guarantees consistent order matching and state across all nodes
- Enables fault-tolerant execution — any node can recover from sequenced history
- Prevents divergence even when nodes join or restart at different times

In the next step, we will introduce **verifiable reads** by having each node sign its `/balance` response, making it possible to verify what data was returned and by whom.

Step 4: Verifiable Balance Reads
--------------------------------

In this step, we enhance the orderbook service by making **balance queries verifiable**. When a client queries `/balance`, the response is signed using the node’s BLS private key.

📄 File: :src:`orderbook/04_verifiable_orderbook_service.py`

Key Concepts
~~~~~~~~~~~~

- Each node has a unique BLS private key
- The `/balance` endpoint returns a signed message
- The signature proves that the node confirmed this balance
- No authentication or sessions are required for reading balances

Why Verifiable Balances?
~~~~~~~~~~~~~~~~~~~~~~~~

When external systems — such as blockchains or other verifiable services — rely on the orderbook, they must be able to **independently confirm user balances** without trusting any single node.

By signing balance responses, the service provides cryptographic proof that a node attested to a specific value. This is essential for secure withdrawals, cross-chain communication, and trustless integration between decentralized services.

Balance Endpoint
~~~~~~~~~~~~~~~~

The `/balance` endpoint now accepts both an address and token:


.. literalinclude:: ../../../examples/orderbook/04_verifiable_orderbook_service.py
   :language: python
   :lines: 57-63

The message is signed using the BLS POP (Proof of Possession) scheme from the blspy library and the resulting signature is included in the API response.

For now, this step ensures that every balance query is individually signed and verifiable. In the :doc:`Signature Aggregation and Verification <verification>` section, we’ll explore how an aggregator can collect signed responses from multiple nodes, combine them into a single BLS signature, and how clients or external services can verify that a quorum of replicas attested to the same value.

