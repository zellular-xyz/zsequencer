Downtime Monitoring Service
============================

This tutorial walks through building a decentralized, verifiable downtime monitoring system step-by-step.

Starting from a simple centralized service, we progressively add decentralized replication, cryptographic proof aggregation, and full BLS-signed downtime reporting across multiple monitoring nodes.

By the end, you will have a complete monitoring system where downtime events and measurements are **cryptographically verifiable** — enabling any third party to independently audit downtime proofs without relying on trust.

01 - Centralized Monitoring Service
-----------------------------------

In the first version, a single centralized server monitors node states by periodically querying their health endpoints.

The server tracks the current state (up or down) of each node and logs events whenever a state change is detected.

📄 File: :src:`downtime_monitoring/01_centralized_monitoring_service.py`

Key Concepts and Implementation Details
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- **Monitoring Nodes**:
  A dictionary ``MONITORED_NODES`` defines the list of nodes being monitored, each identified by an address and a URL.

  .. literalinclude:: ../../../examples/downtime_monitoring/01_centralized_monitoring_service.py
     :language: python
     :start-after: -- start: monitoring nodes config --
     :end-before: -- end: monitoring nodes config --

- **Node State Tracking**:
  Two in-memory structures are maintained:

  - ``nodes_state``: Current up/down status of each node.
  - ``nodes_events``: Historical list of state change events for each node.

  .. literalinclude:: ../../../examples/downtime_monitoring/01_centralized_monitoring_service.py
     :language: python
     :start-after: -- start: tracking node states --
     :end-before: -- end: tracking node states --

- **Health Checking**:
  The ``check_node_state`` function periodically queries each node’s ``/health`` endpoint to determine if it is up or down.

  .. literalinclude:: ../../../examples/downtime_monitoring/01_centralized_monitoring_service.py
     :language: python
     :start-after: -- start: checking node health --
     :end-before: -- end: checking node health --

- **Change Detection**:
  If a node's state has changed since the last check, the change is logged, stored, and timestamped.

  .. literalinclude:: ../../../examples/downtime_monitoring/01_centralized_monitoring_service.py
     :language: python
     :start-after: -- start: detecting node state change --
     :end-before: -- end: detecting node state change --

- **Downtime Calculation**:
  The ``calculate_downtime`` function computes total downtime for a node between two timestamps based on recorded events.

  .. literalinclude:: ../../../examples/downtime_monitoring/01_centralized_monitoring_service.py
     :language: python
     :start-after: -- start: calculating downtime --
     :end-before: -- end: calculating downtime --

- **FastAPI Endpoint**:
  A ``/downtime`` endpoint allows external clients to query a node’s total downtime for a given period.

  .. literalinclude:: ../../../examples/downtime_monitoring/01_centralized_monitoring_service.py
     :language: python
     :start-after: -- start: exposing downtime endpoint --
     :end-before: -- end: exposing downtime endpoint --

- **Background Monitoring Loop**:
  The ``monitor_loop`` function runs in a background thread, randomly selecting nodes to check at fixed intervals.

  .. literalinclude:: ../../../examples/downtime_monitoring/01_centralized_monitoring_service.py
     :language: python
     :start-after: -- start: running monitoring loop --
     :end-before: -- end: running monitoring loop --

Endpoints
~~~~~~~~~

- ``GET /downtime?address=<address>&from_timestamp=<from>&to_timestamp=<to>``:  
  Retrieve the total downtime (in seconds) for a specific node over a given time period.

Example Usage
~~~~~~~~~~~~~

1. **Check Downtime**

.. code-block:: bash

    curl "http://localhost:5000/downtime?address=0xNodeA123&from_timestamp=1714130000&to_timestamp=1714140000"

Limitations
~~~~~~~~~~~

- Single-node, centralized architecture
- No replication or failover
- No cryptographic guarantees on downtime proofs
- Trust is placed entirely in the monitoring server

In the next step, we introduce **replicated monitoring** using Zellular to distribute and synchronize downtime tracking across multiple nodes.

02 - Replicated Monitoring Service
----------------------------------

In this version, the downtime monitoring service is decentralized across multiple nodes using **Zellular**.

Instead of only storing downtime events locally, nodes now **send and retrieve events through the Zellular network**.

This ensures that all replicas observe and apply the same downtime updates, providing resilience and consistency even if some nodes temporarily fail.

📄 File: :src:`downtime_monitoring/02_replicated_monitoring_service.py`

Key Concepts and Implementation Details
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- **Decentralized Event Synchronization**:  
  Downtime events (state changes) are sent to Zellular, making them available to all participating nodes.

  .. literalinclude:: ../../../examples/downtime_monitoring/02_replicated_monitoring_service.py
     :language: python
     :start-after: -- start: sending event to zellular --
     :end-before: -- end: sending event to zellular --

- **Eigenlayer Network Configuration**:  
  Nodes connect to a shared Eigenlayer network and configure a threshold percentage for batching updates.

  .. literalinclude:: ../../../examples/downtime_monitoring/02_replicated_monitoring_service.py
     :language: python
     :start-after: -- start: configuring eigenlayer network --
     :end-before: -- end: configuring eigenlayer network --

- **Two Separate Loops**:

  - `monitor_loop`: Periodically checks node health and sends downtime events if a change is detected.
  - `process_loop`: Continuously pulls downtime events from Zellular and applies them to the local event log.

  .. literalinclude:: ../../../examples/downtime_monitoring/02_replicated_monitoring_service.py
     :language: python
     :start-after: -- start: running monitor and process loops --
     :end-before: -- end: running monitor and process loops --

- **Event-based Updates**:  
  Local node state and history are updated **only after** receiving and applying a downtime event.

  .. literalinclude:: ../../../examples/downtime_monitoring/02_replicated_monitoring_service.py
     :language: python
     :start-after: -- start: applying event to local state --
     :end-before: -- end: applying event to local state --

Limitations
~~~~~~~~~~~

- Still no cryptographic proof of downtime (events are trusted as-is)
- Zellular ensures consistency but not verifiability
- Anyone who controls event submission could falsify downtime data

In the next step, we introduce **BLS signatures and decentralized attestation** to verify downtime claims cryptographically.

03 - Proof Aggregating Monitoring Service
------------------------------------------

In this version, downtime events are no longer trusted blindly.  
Before accepting a node's state change, the monitoring node **gathers signed confirmations** from other nodes.

These confirmations are **BLS aggregated** into a single compact proof, ensuring that a majority agrees on the state change before it is accepted and broadcast through Zellular.

This upgrade introduces **cryptographic verifiability** to downtime monitoring.

📄 File: :src:`downtime_monitoring/03_proof_aggregating_monitoring_service.py`

Key Concepts and Implementation Details
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- **BLS-Based State Confirmation**:
  Each downtime monitoring node signs the current state (up/down) of a node together with a timestamp.

  .. literalinclude:: ../../../examples/downtime_monitoring/03_proof_aggregating_monitoring_service.py
     :language: python
     :start-after: -- start: signing state confirmation --
     :end-before: -- end: signing state confirmation --

- **Asynchronous State Gathering**:
  When a change is detected, the monitoring node queries other nodes for their signed state observations asynchronously.

  .. literalinclude:: ../../../examples/downtime_monitoring/03_proof_aggregating_monitoring_service.py
     :language: python
     :start-after: -- start: querying state from monitoring nodes --
     :end-before: -- end: querying state from monitoring nodes --

- **Signature Aggregation and Threshold Enforcement**:
  Only if a 2/3 majority of nodes agree, their individual BLS signatures are aggregated into a single proof.

  .. literalinclude:: ../../../examples/downtime_monitoring/03_proof_aggregating_monitoring_service.py
     :language: python
     :start-after: -- start: aggregating valid signatures --
     :end-before: -- end: aggregating valid signatures --

- **Verifiable Event Broadcasting**:
  The aggregated proof is attached to the downtime event and sent to Zellular.  
  All replicas verify the proof before accepting and applying the event.

  .. literalinclude:: ../../../examples/downtime_monitoring/03_proof_aggregating_monitoring_service.py
     :language: python
     :start-after: -- start: verifying and applying events --
     :end-before: -- end: verifying and applying events --

Limitations
~~~~~~~~~~~

- Still relies on a single node to calculate and report downtime
- Cryptographic proofs exist for state changes, but not for total downtime

In the next step, we extend BLS verification to cover downtime **calculations**, ensuring majority agreement on reported downtime values.

04 - Verifiable Downtime Monitoring Service
-------------------------------------------

In a decentralized monitoring system, it's not enough to track downtime — the correctness of the reported downtime must also be verifiable.

When other services (such as reward managers, slashing modules, or external analytics) rely on this monitoring system, they must be able to trust the downtime data. Verifiable downtime proofs allow these external systems to independently confirm that nodes report downtime accurately and consistently, without relying purely on trust.

By signing each downtime response with a BLS key:

- The monitoring node attests to the specific downtime value it calculated.
- The signature can be independently verified or aggregated with signatures from other nodes.
- Clients can detect misreporting or inconsistencies across different monitoring nodes.

This verifiability forms the foundation for **trustless reward distribution**, **slashing mechanisms**, and **interoperable decentralized monitoring**, ensuring resilience against dishonest participants.


📄 File: :src:`downtime_monitoring/04_verifiable_monitoring_service.py`

Key Concepts and Implementation Details
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- **Signed Downtime Calculation**:
  Every node signs its calculated downtime for a given address and time period.

.. literalinclude:: ../../../examples/downtime_monitoring/04_verifiable_monitoring_service.py
   :language: python
   :start-after: -- start: signing downtime report --
   :end-before: -- end: signing downtime report --

- **Downtime Aggregation**:
  A node can request downtime values from other monitoring nodes, aggregate valid signatures, and verify majority consensus.

.. literalinclude:: ../../../examples/downtime_monitoring/04_verifiable_monitoring_service.py
   :language: python
   :start-after: -- start: aggregating downtime responses --
   :end-before: -- end: aggregating downtime responses --

- **New `/aggregate_downtime` Endpoint**:
  A new FastAPI route triggers aggregation of downtime proofs and returns a cryptographically verifiable result.

.. literalinclude:: ../../../examples/downtime_monitoring/04_verifiable_monitoring_service.py
   :language: python
   :start-after: -- start: downtime aggregation endpoint --
   :end-before: -- end: downtime aggregation endpoint --

