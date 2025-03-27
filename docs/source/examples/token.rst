Token as a Verifiable Service
=============================

This guide walks through transforming a simple token service into a decentralized and verifiable application using the Zellular Sequencer.

We follow a progressive enhancement model, starting from a basic session-based FastAPI service, and incrementally evolving it into a replicated and cryptographically verifiable system.

Each step corresponds to a real code implementation in the Zellular `examples/token <https://github.com/zellular-xyz/zsequencer/blob/usecases/examples/token/>`_ directory.

Step 1: Centralized Token Service
---------------------------------

In the first stage, we build a basic centralized token service using FastAPI. User sessions are tracked with server-side cookies, and balances are stored in-memory.

📄 File: `01_centralized_token_service.py <https://github.com/zellular-xyz/zsequencer/blob/usecases/examples/token/01_centralized_token_service.py>`_

Key Concepts
~~~~~~~~~~~~

- **Framework**: FastAPI
- **Session Management**: Via `SessionMiddleware`
- **Authentication**: Username/password stored in memory
- **Token State**: Python `dict` holding balances
- **Transfer Logic**: Requires an active session

Endpoints
~~~~~~~~~

- `POST /login`: Authenticate with username/password
- `POST /transfer`: Send tokens from the logged-in user
- `GET /balance?username=<username>`: Query balance

Example Usage
~~~~~~~~~~~~~

1. **Login**

.. code-block:: bash

    curl -X POST http://localhost:5001/login \
         -H "Content-Type: application/json" \
         -d '{"username": "user1", "password": "pass1"}' \
         -c cookies.txt

2. **Transfer**

.. code-block:: bash

    curl -X POST http://localhost:5001/transfer \
         -H "Content-Type: application/json" \
         -d '{"receiver": "user2", "amount": 50}' \
         -b cookies.txt

3. **Check Balance**

.. code-block:: bash

    curl http://localhost:5001/balance?username=user1

Limitations
~~~~~~~~~~~

- Single-node, centralized architecture
- No cryptographic guarantees
- Relies on server-side session for authentication

In the next step, we replace the session system with cryptographic signatures for stateless and verifiable authentication.

Step 2: Signature-Based Token Service
-------------------------------------

This version removes session-based auth and introduces **Ethereum-style digital signatures**. Users sign transfer messages off-chain using their private key. The backend verifies these signatures and recovers the sender address directly from the signed message.

📄 File: `02_signature_based_token_service.py <https://github.com/zellular-xyz/zsequencer/blob/usecases/examples/token/02_signature_based_token_service.py>`_

Key Concepts
~~~~~~~~~~~~

- Stateless authentication using ECDSA signatures
- Compatible with wallets like MetaMask or `eth_account`
- Server no longer stores user credentials or sessions

Endpoints
~~~~~~~~~

- `POST /transfer`: Send a signed transfer request
- `GET /balance?address=0x...`: Query token balance

Signing Format
~~~~~~~~~~~~~~

Users must sign a message in this format:

.. code-block:: text

   Transfer {amount} to {receiver}

For example:

.. code-block:: text

   Transfer 10 to 0xAbc123...

Client-Side Signing (Python Example)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from eth_account import Account
   from eth_account.messages import encode_defunct

   private_key = "0x..."
   message = f"Transfer {amount} to {receiver}"
   encoded = encode_defunct(text=message)
   signed = Account.sign_message(encoded, private_key=private_key)

   signature = signed.signature.hex()
   sender = Account.from_key(private_key).address

Backend Verification
~~~~~~~~~~~~~~~~~~~~

On the server:

.. code-block:: python

   message = f"Transfer {amount} to {receiver}"
   encoded = encode_defunct(text=message)
   recovered = Account.recover_message(encoded, signature=signature)

   if recovered.lower() != sender.lower():
       raise HTTPException(status_code=401, detail="Invalid signature")

   if balances.get(sender, 0) < amount:
       raise HTTPException(status_code=400, detail="Insufficient balance")

   balances[sender] -= amount
   balances[receiver] = balances.get(receiver, 0) + amount

Request Format
~~~~~~~~~~~~~~

.. code-block:: json

   {
     "sender": "0xYourAddress",
     "receiver": "0xRecipientAddress",
     "amount": 10,
     "signature": "0x..."
   }

Test Script
~~~~~~~~~~~

To simplify development, a helper script is included:

📄 File: `transfer.py <https://github.com/zellular-xyz/zsequencer/blob/usecases/examples/token/transfer.py>`_

This script:

- Loads a private key
- Signs a message
- Sends it to the `/transfer` endpoint

Run it with:

.. code-block:: bash

   python examples/token/transfer.py

Example Usage
~~~~~~~~~~~~~

1. **Transfer tokens**

.. code-block:: bash

   curl -X POST http://localhost:5001/transfer \
        -H "Content-Type: application/json" \
        -d '{
              "sender": "0x...",
              "receiver": "0x...",
              "amount": 10,
              "signature": "0x..."
            }'

2. **Check balance**

.. code-block:: bash

   curl http://localhost:5001/balance?address=0xYourAddress

Why This Matters
~~~~~~~~~~~~~~~~

- Cryptographic authentication without storing secrets
- Stateless backend logic
- Ready for replication in decentralized networks

In Step 3, we integrate the **Zellular Sequencer** to distribute and replicate transfer updates across nodes.

Step 3: Replicated Token Service
--------------------------------

In this step, we integrate the **Zellular Sequencer** to replicate the token state across multiple nodes. Transfer requests are no longer applied directly when submitted — instead, they are sent to the Zellular Sequencer, which sequences them and broadcasts them to all participating replicas.

Each replica node independently fetches the same ordered batch of transfers and applies them locally. This ensures all nodes remain consistent, even in the presence of faults or restarts.

📄 File: `03_replicated_token_service.py <https://github.com/zellular-xyz/zsequencer/blob/usecases/examples/token/03_replicated_token_service.py>`_

Key Concepts
~~~~~~~~~~~~

- Uses the Zellular Python SDK (`Zellular(...)`)
- Transfers are submitted via `zellular.send(...)`
- Replica nodes pull and apply batches using `zellular.batches()`
- Transfers are still signed and verified using the same logic from Step 2

Transfer Submission
~~~~~~~~~~~~~~~~~~~

Transfers are submitted via the `/transfer` route, verified as before, and then sent to the Zellular Sequencer:

.. code-block:: python

   txs = [{
       "sender": data.sender,
       "receiver": data.receiver,
       "amount": data.amount,
       "signature": data.signature
   }]
   zellular.send(txs, blocking=False)

This appends the transfer to the global sequence shared by all replicas.

Processing Batches from Zellular
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Each replica runs a background loop using the SDK to process batches:

.. code-block:: python

   for batch, index in zellular.batches():
       txs = json.loads(batch)
       for tx in txs:
           __transfer(tx)

The `__transfer(tx)` function:

1. Reconstructs the signed message
2. Verifies the signature
3. Checks sender balance
4. Applies the transfer if valid

This ensures all replicas apply transfers **in the same order** and reach the same balances.

Full Transfer Verification Logic
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   def __transfer(data: Dict[str, Any]) -> None:
       sender, receiver, amount, signature = (
           data["sender"], data["receiver"], data["amount"], data["signature"]
       )
       message = f"Transfer {amount} to {receiver}"
       if not verify_signature(sender, message, signature):
           logger.error(f"Invalid signature: {data}")
           return
       if balances.get(sender, 0) < amount:
           logger.error(f"Insufficient balance: {data}")
           return
       balances[sender] -= amount
       balances[receiver] = balances.get(receiver, 0) + amount
       logger.info(f"Transfer successful: {data}")

Why This Matters
~~~~~~~~~~~~~~~~

- Ensures all nodes apply transfers in the same global order
- Enables fault-tolerant, deterministic replication
- Balances remain consistent even if nodes crash or restart

In Step 4, we’ll introduce **verifiable reads**: users can query balances and verify the response using aggregated BLS signatures from the token replicas.

Step 4: Verifiable Token Service
--------------------------------

In this step, we make balance queries verifiable by cryptographically signing every `/balance` response using **BLS signatures**. Each node signs the message with its own private key, allowing external services to confirm the authenticity of the returned value.

📄 File: `04_verifiable_token_service.py <https://github.com/zellular-xyz/zsequencer/blob/usecases/examples/token/04_verifiable_token_service.py>`_

Key Concepts
~~~~~~~~~~~~

- `/balance` responses are now BLS-signed
- Clients can collect signed values from multiple nodes
- These signatures can later be aggregated and verified (see future section)

Why Verifiable Reads?
~~~~~~~~~~~~~~~~~~~~~

In a decentralized setting, it's not enough to replicate state — the **correctness of the state must also be verifiable**.

When other services (such as wallets, exchanges, or cross-chain systems) rely on the token service, they must be able to trust the values returned from balance queries. Verifiable reads enable these external systems to **independently confirm that a node is reporting accurate, untampered state**, without relying on that node’s honesty.

By signing each balance response with a BLS key:

- The node **attests to the specific value** it returned
- The signature can be later verified or aggregated with others
- Clients can detect misreporting or inconsistency across nodes

This forms the foundation for **trustless interoperability** between services that read from each other — essential for building tamper-proof decentralized infrastructure.

Balance Endpoint
~~~~~~~~~~~~~~~~

The `/balance` endpoint signs the message before returning it:

.. code-block:: python

   from blspy import PopSchemeMPL

   @app.get("/balance")
   async def balance(address: str) -> Dict[str, Any]:
       balance = balances.get(address, 0)
       message = f"Address: {address}, Balance: {balance}".encode("utf-8")
       signature = PopSchemeMPL.sign(sk, message)
       return {
           "address": address,
           "balance": balance,
           "signature": str(signature)
       }

The message is signed using the BLS POP (Proof of Possession) scheme from the `blspy` library and the resulting `signature` is included in the API response.

For now, this step ensures that every balance query is individually signed and verifiable. In the :doc:`Signature Aggregation and Verification <verification>` section, we’ll explore how an aggregator can collect signed responses from multiple nodes, combine them into a single BLS signature, and how clients or external services can verify that a quorum of replicas attested to the same value.
