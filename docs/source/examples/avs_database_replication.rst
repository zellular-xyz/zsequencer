AVS Database Replication using Zellular
=======================================

📄 Guide: `Leveraging Zellular for Decentralized Database Replication within an AVS <https://medium.com/zellular/leveraging-zellular-for-decentralized-database-replication-within-an-avs-89d75c359432>`_

Zellular enables AVS developers to replicate shared state across a decentralized network of nodes — efficiently, verifiably, and without relying on on-chain storage.

This pattern ensures that all nodes maintain the same view of critical data, such as uptime logs, validator metrics, or other consensus-relevant inputs.

Replicating State Between Nodes
-------------------------------

Downtime logging is just one use case of a broader capability: **synchronizing shared data across AVS nodes**. Zellular allows any structured data to be replicated in a consistent, globally ordered way.

Each node receives the same sequence of updates from the Zellular Sequencer and applies them locally. This guarantees that all nodes independently reach the same view of the system state.

Zellular ensures:

- ✅ **Deterministic ordering**: Nodes apply updates in the same global sequence
- ✅ **Fault tolerance**: Nodes that restart can replay the full history
- ✅ **Verifiability**: Events may include BLS-signed attestations
- ✅ **No blockchain dependency**: Operates off-chain with API simplicity

Use Case: Logging Node Downtime
-------------------------------

In AVS ecosystems where uptime matters, it’s essential to keep an accurate, shared record of which operators were available or unreachable.

Zellular allows AVS nodes to coordinate on validated downtime reports without relying on a smart contract or centralized storage.

The workflow typically looks like:

1. Aggregators detect suspected downtime for a node
2. They query other AVS nodes to confirm it
3. Once a quorum of confirmations is collected, the aggregator posts a downtime event to Zellular
4. All nodes listen for new events and store them after validating

Posting Downtime Logs to Zellular
---------------------------------

Aggregators post confirmed events to Zellular with BLS signatures attached:

.. code-block:: python

   zellular = zellular.Zellular("avs-liveness-checker", base_url)
   zellular.send([{
       'node': 8,
       'event_type': 'down',
       'timestamp': 1732522695,
       'sig': '0x23a3...46da'
   }])

Each AVS node independently listens for new events:

.. code-block:: python

   zellular = zellular.Zellular("avs-liveness-checker", base_url)
   for batch, index in zellular.batches(after=index):
       events = json.loads(batch)
       for event in events:
           if verify(event):
               add_event_log(event)

If verification passes and the event meets the AVS quorum threshold, the node appends it to its local database.

Why It Matters
--------------

- ✅ **No missed events**: All nodes observe and process the same sequence
- ✅ **Global consistency**: All replicas store the same event log
- ✅ **Cryptographic proof**: Signatures from other nodes can be attached
- ✅ **Efficient and simple**: No contract deployment, no gas, no RPCs

This enables AVSs to answer questions like *“how many times was node 8 down this epoch?”* with full confidence in the result — without requiring blockchain infrastructure.

Zellular enables high-integrity state replication across AVS nodes, providing the foundation for decentralized accountability, logging, and auditability — at a fraction of the cost and complexity of on-chain alternatives.
