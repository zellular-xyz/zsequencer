Zellular Sequencer
==================

`Replicating <https://en.wikipedia.org/wiki/State_machine_replication>`_ centralised services across multiple nodes creates a decentralised system that remains robust, even if some nodes fail or act maliciously—this is the essence of `Byzantine Fault Tolerance <https://en.wikipedia.org/wiki/Byzantine_fault>`_.

The first phase in decentralizing a centralized service using this approach is to replace the conventional username/password login with signature-based authentication at every place where users send their requests to enable each node to independently verify those requests.

In the second phase, ensuring that all replicated nodes maintain the same data or state is crucial. This requires all nodes to receive and process user-signed requests in the exact same order. If nodes process updates in different orders, they can become out of sync. The **Zellular Sequencer** addresses this challenge by making sure that every node in the network processes every request in the same sequence.

In Zellular Sequencer, one of the network nodes, the Sequencer, takes the leader role for sequencing tasks. User-signed requests received by a node are applied to the database only after being sent to the leader and received back along with other nodes’ requests in a consistent order.


.. figure:: images/image1.png
  :align: center
  :width: 500
  :alt: Zellular Sequencer Architecture


If the Sequencer malfunctions—by going offline, censoring requests, or sending inconsistent orders—other nodes can challenge its actions. Should enough nodes agree, the Sequencer's role will seamlessly transfer to a new leader. This mechanism makes the Zellular Sequencer a Byzantine Fault Tolerant (BFT) service, facilitating sequencing without a single point of failure.

.. note::

   This project is under active development.

Contents
--------

.. toctree::

   sdk
   integration
   protocol
