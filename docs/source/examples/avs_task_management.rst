AVS Task Management using Zellular
==================================

📄 Guide: `Enhancing AVS Efficiency Using Zellular Sequencer for Task Management <https://medium.com/zellular/enhancing-avs-efficiency-using-zellular-sequencer-for-task-management-b10c36c56c79>`_

Zellular provides a cost-efficient, decentralized, and high-throughput task manager for AVSs built on EigenLayer. It replaces on-chain task coordination with a lightweight, verifiable messaging system.

This example demonstrates how to update the `incredible-squaring-avs-python <https://github.com/zellular-xyz/incredible-squaring-avs-python>`_ implementation to use Zellular instead of a blockchain smart contract.

AVSs & Task Management
----------------------

AVSs (Autonomous Variable Services) rely on coordinated task execution by validators. Traditionally, AVS developers emit tasks using smart contracts and rely on blockchain infrastructure (RPCs, subgraphs) to distribute them to nodes.

This introduces cost, latency, and reliance on centralized services.

Zellular offers a simpler alternative. It can be used as a **decentralized event queue** to distribute tasks among AVS nodes, with verifiable delivery and no blockchain dependency.

Step 1: Connecting to Zellular
------------------------------

Replace the smart contract connection logic:

.. code-block:: python

   def __load_task_manager(self):
       web3 = Web3(Web3.HTTPProvider(self.config["eth_rpc_url"]))
       ...
       self.task_manager = web3.eth.contract(...)

With a direct connection to the Zellular network:

.. code-block:: python

   def __load_zellular(self):
       operators = zellular.get_operators()
       base_url = random.choice(operators)["socket"]
       app_name = "incredible-squaring"
       self.zellular = zellular.Zellular(app_name, base_url)

Step 2: Posting Tasks to Zellular
---------------------------------

Replace on-chain transaction logic:

.. code-block:: python

   def send_new_task(self, i):
       tx = self.task_manager.functions.createNewTask(...).build_transaction(...)
       ...
       receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash)

       event = self.task_manager.events.NewTaskCreated().process_log(receipt['logs'][0])
       task_index = event['args']['taskIndex']

With a direct Zellular submission:

.. code-block:: python

   def send_new_task(self, i):
       task = {
           "numberToBeSquared": i,
           "quorumNumbers": [0],
           "quorumThresholdPercentage": 100,
       }
       task_index = self.zellular.send([task], blocking=True)

Step 3: Getting Tasks from Zellular
-----------------------------------

Replace event polling from the smart contract:

.. code-block:: python

   def start(self):
       event_filter = self.task_manager.events.NewTaskCreated.create_filter(fromBlock="latest")
       while True:
           for event in event_filter.get_new_entries():
               self.process_task_event(event)

With deterministic polling from the sequencer:

.. code-block:: python

   def start(self):
       index = self.zellular.get_last_finalized()["index"]
       for batch, index in self.zellular.batches(after=index):
           events = json.loads(batch)
           for i, event in enumerate(events):
               self.process_task_event(event)

Note: This is a simplified demonstration and not a complete working integration.

Zellular vs. Blockchain for AVS Task Management
-----------------------------------------------

**Costs and Throughput**

- Blockchain-based task management incurs significant gas fees.
- Reading from chains often depends on centralized RPC or subgraph providers.
- Each AVS node pays these costs independently, multiplying expenses.
- Zellular removes these costs and supports much higher throughput.

**Decentralization and Security**

- With blockchains, most AVS nodes rely on third-party infrastructure to fetch events.
- Zellular removes this dependency: any Zellular node can serve data directly.
- Every response can be verified using an aggregated BLS signature — no need to trust a single node.

Zellular offers a simpler, cheaper, and more verifiable way to coordinate tasks across AVS nodes — without requiring smart contracts or subgraphs.
