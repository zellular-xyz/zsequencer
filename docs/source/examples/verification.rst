Signature Aggregation and Verification
======================================

This section explains how to aggregate signed balance responses from multiple nodes and verify that a **quorum of replicas attested to the same value** using BLS signature aggregation.

All examples here are located in :src: `verification` directory.

Overview
--------

- Each replica signs a balance query using its private BLS key
- These signatures are returned via `/balance` APIs
- A client (e.g. an exchange) can query multiple nodes
- If enough nodes return the same value and valid signatures, they are aggregated
- The aggregated signature acts as a **cryptographic proof** of correctness

Nodes and Configuration
-----------------------

Nodes are listed in a shared config file:

📄 File: :src:`verification\nodes.json`

Each node entry includes:

- A `url` for the `/balance` endpoint
- A `pubkey` string representing its BLS public key

Example:

.. code-block:: json

   {
     "node1": {
       "url": "http://localhost:5001/balance",
       "pubkey": "aabbcc..."
     },
     "node2": {
       "...": "..."
     }
   }

Aggregating Signatures
----------------------

📄 File: :src:`verification/signature_aggregator.py`

This script:

- Sends balance queries to all nodes
- Verifies each response’s signature
- Filters out any invalid or inconsistent responses
- Aggregates the valid BLS signatures (using `PopSchemeMPL.aggregate`)
- Ensures that at least **2/3 of nodes** agreed on the same value

Run the script:

.. code-block:: bash

   python examples/verification/signature_aggregator.py

The result includes:

- The original signed message
- The aggregated BLS signature
- List of nodes that failed to respond or disagreed

Verifying Aggregated Signatures
-------------------------------

📄 File: :src:`verification/verify_aggregated_signature.py`

This implementation uses the **EigenLayer-style BLS verification model**, where the verifier starts with a **precomputed aggregate public key** representing all expected nodes.

When a subset of nodes fail to sign (or return invalid responses), their public keys are effectively **subtracted** from the aggregated key — not by using subtraction directly (which `blspy` doesn't support), but by **adding the negation** of each missing key:

.. literalinclude:: ../../../examples/verification/verify_aggregated_signature.py
   :language: python
   :start-after: -- start: subtracting nonsigners --
   :end-before: -- end: subtracting nonsigners --

This adjusted public key reflects only the nodes that signed.

The final verification step looks like:

.. literalinclude:: ../../../examples/verification/verify_aggregated_signature.py
   :language: python
   :start-after: -- start: verifying signature --
   :end-before: -- end: verifying signature --

This verifies that a quorum of nodes cryptographically agreed on the result.

Benefits of This Approach
-------------------------

- ✅ Efficient: avoids re-aggregating signer keys on each query
- ✅ Optimized for the honest majority case (typical in production)
- ✅ Allows caching the full key and incrementally adjusting
- ✅ Matches EigenLayer's BLS verification strategy
