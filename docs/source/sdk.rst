Zellular SDK
===============

Dependencies
------------

To use zellular SDK, you'll need to install the `MCL <https://github.com/herumi/mcl>`_ native library. Follow these steps:

.. code-block:: bash

    sudo apt install libgmp3-dev
    wget https://github.com/herumi/mcl/archive/refs/tags/v1.93.zip
    unzip v1.93.zip
    cd mcl-1.93
    mkdir build
    cd build
    cmake ..
    make
    make install

Installation
------------

Install the zelluar SDK via pip:

.. code-block:: bash

    pip install zellular

Usage
-----

Network Architectures
~~~~~~~~~~~~~~~~~~~~~

Zellular supports multiple network architectures:

1. **EigenlayerNetwork**: For interacting with Zellular deployed on EigenLayer.
2. **StaticNetwork**: For local testing or proof-of-authority deployments with a fixed set of operators.

Setting Up With EigenLayer Network
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from zellular import Zellular, EigenlayerNetwork

    network = EigenlayerNetwork(
        subgraph_url="https://api.studio.thegraph.com/query/95922/avs-subgraph/version/latest",
        threshold_percent=67
    )

    app_name = "simple_app"
    zellular = Zellular(app_name, network)

Setting Up With Static Network
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    import json
    from zellular import Zellular, StaticNetwork

    with open("nodes.json") as f:
        nodes_data = json.load(f)

    network = StaticNetwork(nodes_data, threshold_percent=67)
    app_name = "simple_app"
    zellular = Zellular(app_name, network)

Active Operators and Gateway Selection
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

You can optionally specify a ``gateway`` parameter to connect to a specific operator, or let Zellular select one automatically.

.. code-block:: python

    from zellular import Zellular, EigenlayerNetwork

    network = EigenlayerNetwork(
        subgraph_url="https://api.studio.thegraph.com/query/95922/avs-subgraph/version/latest",
        threshold_percent=67
    )

    zellular_auto = Zellular("simple_app", network)

    custom_gateway = "http://your-custom-operator:6001"
    zellular_custom = Zellular("simple_app", network, gateway=custom_gateway)

Manually Fetch Active Operators:

.. code-block:: python

    import asyncio
    from pprint import pprint
    from zellular import Zellular, EigenlayerNetwork

    network = EigenlayerNetwork(
        subgraph_url="https://api.studio.thegraph.com/query/95922/avs-subgraph/version/latest",
        threshold_percent=67
    )

    zellular = Zellular("simple_app", network)

    active_operators = asyncio.run(zellular.get_active_operators("simple_app"))
    pprint(active_operators)

    if active_operators:
        random_operator = active_operators[0]
        print(f"Selected operator: {random_operator.socket}")

Active operator selection helps:

- Find healthy nodes for your application
- Ensure operators are running the latest version
- Ensure up-to-date consensus state

Posting Transactions
~~~~~~~~~~~~~~~~~~~~

Zellular sequences transactions in batches:

.. code-block:: python

    import time
    from uuid import uuid4
    from zellular import Zellular, EigenlayerNetwork

    network = EigenlayerNetwork(
        subgraph_url="https://api.studio.thegraph.com/query/95922/avs-subgraph/version/latest",
        threshold_percent=67
    )

    app_name = "simple_app"
    zellular = Zellular(app_name, network)

    t = int(time.time())
    txs = [{"operation": "foo", "tx_id": str(uuid4()), "t": t} for _ in range(5)]

    index = zellular.send(txs, blocking=True)

.. note::

    You can add your app to the Zellular test network using:

    .. code-block:: bash

        curl -X POST https://www.zellular.xyz/testnet/apps -H "Content-Type: application/json" -d '{"app_name": "your-app-name"}'

Fetching and Verifying Transactions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Zellular allows trustless reading of finalized transactions using aggregated BLS signatures.

.. code-block:: python

    import json
    from zellular import Zellular, EigenlayerNetwork

    network = EigenlayerNetwork(
        subgraph_url="https://api.studio.thegraph.com/query/95922/avs-subgraph/version/latest",
        threshold_percent=67
    )

    app_name = "simple_app"
    zellular = Zellular(app_name, network)

    for batch, index in zellular.batches(after=0):
        txs = json.loads(batch)
        for i, tx in enumerate(txs):
            print(index, i, tx)

Example output:

.. code-block:: text

    app: simple_app, index: 1, result: True
    app: simple_app, index: 2, result: True
    583 0 {'tx_id': '7eaa...2101', 'operation': 'foo', 't': 1725363009}
    ...

To start reading from the latest finalized batch:

.. code-block:: python

    index = zellular.get_last_finalized()["index"]
    for batch, index in zellular.batches(after=index):
        ...

