Token as a Verifiable Service
=============================

This guide walks through transforming a simple token service into a decentralized and verifiable application using the Zellular Sequencer.

We follow a progressive enhancement model, starting from a basic session-based FastAPI service, and incrementally evolving it into a replicated and cryptographically verifiable system.

Each step corresponds to a real code implementation in the Zellular :src:`token` directory.

Step 1: Centralized Token Service
---------------------------------

In the first stage, we build a basic centralized token service using FastAPI. User sessions are tracked with server-side cookies, and balances are stored in-memory.

📄 File: :src:`token/01_centralized_token_service.py`

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

📄 File: :src:`token/02_signature_based_token_service.py`

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

.. literalinclude:: ../../../examples/token/transfer.py
   :language: python
   :start-after: -- start: signing transfer --
   :end-before: -- end: signing transfer --

Backend Verification
~~~~~~~~~~~~~~~~~~~~

On the server:

.. literalinclude:: ../../../examples/token/02_signature_based_token_service.py
   :language: python
   :start-after: -- start: verifying signature before transfer --
   :end-before: -- end: verifying signature before transfer --

Test Script
~~~~~~~~~~~

To simplify development, a helper script is included:

📄 File: :src:`token/transfer.py`

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

📄 File: :src:`token/03_replicated_token_service.py`

Key Concepts
~~~~~~~~~~~~

- Uses the Zellular Python SDK (`Zellular(...)`)
- Transfers are submitted via `zellular.send(...)`
- Replica nodes pull and apply batches using `zellular.batches()`
- Transfers are still signed and verified using the same logic from Step 2

Transfer Submission
~~~~~~~~~~~~~~~~~~~

Transfers are submitted via the `/transfer` route, verified as before, and then sent to the Zellular Sequencer:

.. literalinclude:: ../../../examples/token/03_replicated_token_service.py
   :language: python
   :start-after: -- start: submitting transfer to zellular --
   :end-before: -- end: submitting transfer to zellular --


This appends the transfer to the global sequence shared by all replicas.

Processing Batches from Zellular
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Each replica runs a background loop using the SDK to process batches:

.. literalinclude:: ../../../examples/token/03_replicated_token_service.py
   :language: python
   :start-after: -- start: processing loop --
   :end-before: -- end: processing loop --

The `apply_transfer(tx)` function:

1. Reconstructs the signed message
2. Verifies the signature
3. Checks sender balance
4. Applies the transfer if valid

This ensures all replicas apply transfers **in the same order** and reach the same balances.

Full Transfer Verification Logic
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. literalinclude:: ../../../examples/token/03_replicated_token_service.py
   :language: python
   :start-after: -- start: applying transfer --
   :end-before: -- end: applying transfer --

Why This Matters
~~~~~~~~~~~~~~~~

- Ensures all nodes apply transfers in the same global order
- Enables fault-tolerant, deterministic replication
- Balances remain consistent even if nodes crash or restart

In Step 4, we’ll introduce **verifiable reads**: users can query balances and verify the response using aggregated BLS signatures from the token replicas.

.. _signed-balance-token-service:

Step 4: Signed Balance Token Service
------------------------------------

In this step, we introduce cryptographic signatures for balance responses. Each replica node now signs its own ``/balance`` response using a **BLS signature**, which allows external clients to confirm that the node is attesting to a specific value.

📄 File: :src:`token/04_signed_balance_token_service.py`

Key Concepts
~~~~~~~~~~~~

- ``/balance`` responses are now individually signed using BLS
- Each node attests to the correctness of its response
- Clients can optionally verify the individual signature using the node’s public key

Why Signed Responses?
~~~~~~~~~~~~~~~~~~~~~

In a decentralized environment, it’s important to ensure that values returned from public APIs can be **cryptographically authenticated**.

By signing the balance response:

- The node proves it is accountable for the value it returned
- Clients can verify the signature independently
- This enables detection of tampered or inconsistent responses

This step lays the groundwork for **verifiable reads**, where multiple nodes agree on the same value.

Balance Endpoint
~~~~~~~~~~~~~~~~

Each node signs its ``/balance`` response using BLS:

.. literalinclude:: ../../../examples/token/04_signed_balance_token_service.py
   :language: python
   :start-after: -- start: checking balance --
   :end-before: -- end: checking balance --

In Step 5, we’ll show how to **aggregate** these signed responses from multiple nodes to produce a **single verifiable proof** that a quorum attested to the same value.

.. _verifiable-token-service:

Step 5: Verifiable Token Service
--------------------------------

In this final step, we introduce a new endpoint that aggregates signed balance responses from multiple nodes and returns a **single BLS signature** as proof.

📄 File: :src:`token/05_verifiable_token_service.py`

Key Concepts
~~~~~~~~~~~~

- Aggregator node queries multiple replicas for their signed balances
- Only responses that match the expected value are included in the quorum
- The resulting BLS signatures are **aggregated into a single proof**
- Clients can verify the aggregated signature using the **aggregated public key** (with excluded non-signers)

Why Signature Aggregation?
~~~~~~~~~~~~~~~~~~~~~~~~~~

In a decentralized token system, it's not enough for individual nodes to return signed balances. What matters is whether a **majority of them agree** on the same value.

Step 5 introduces **signature aggregation**, allowing clients to:

- Collect individual BLS-signed balance responses
- Aggregate them into a **single compact proof**
- Verify that a **quorum of nodes attested** to the same balance

This is especially important for **external independent services** — such as cross-chain bridges or decentralized exchanges — that consume balance data from the token service. These services need **cryptographic assurance** that a balance was not only signed, but also **agreed upon by a majority of nodes**, without trusting any single replica.

By verifying the aggregated signature, clients can confirm not only the value itself but that **a threshold of honest nodes agrees** with it — enabling **trustless interoperability** across decentralized infrastructure.

Aggregation Logic
~~~~~~~~~~~~~~~~~

The aggregator queries all replicas and collects signed balance responses:

.. literalinclude:: ../../../examples/token/05_verifiable_token_service.py
   :language: python
   :start-after: -- start: querying nodes for signed balances --
   :end-before: -- end: querying nodes for signed balances --

Valid signatures that match the expected balance are combined:

.. literalinclude:: ../../../examples/token/05_verifiable_token_service.py
   :language: python
   :start-after: -- start: aggregating matching signatures --
   :end-before: -- end: aggregating matching signatures --

The final response includes:

- The agreed-upon balance
- The aggregated BLS signature
- The list of non-signing nodes

Verification Example
~~~~~~~~~~~~~~~~~~~~

To verify the aggregated signature, clients subtract non-signers' public keys from the aggregate key and verify the result.

📄 File: :src:`token/verify_aggregated_signature.py`

.. literalinclude:: ../../../examples/token/verify_aggregated_signature.py
   :language: python
   :start-after: -- start: subtracting non-signers --
   :end-before: -- end: subtracting non-signers --

.. literalinclude:: ../../../examples/token/verify_aggregated_signature.py
   :language: python
   :start-after: -- start: verifying signature --
   :end-before: -- end: verifying signature --

Why This Matters
~~~~~~~~~~~~~~~~

- Enables **auditable consensus** from decentralized nodes
- Promotes **interoperability** with other offchain or onchain systems
- Reduces trust assumptions to **cryptographic validation**

You now have a fully replicated, consistent, and **deterministic orderbook service** built with Zellular.
