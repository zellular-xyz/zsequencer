Zellular SDK
============

Dependencies
------------

To use zelluar.py, you'll need to install the MCL native library. Follow these steps to install it:

.. code-block:: shell

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

Install the zelluar.py package via pip:

.. code-block:: shell

    pip install zellular

Getting Nodes
-------------

Zellular Testnet is deployed on the EigenLayer Holesky network. The list of operators can be queried using the following `curl` command:

.. code-block:: shell

    curl \
      --header 'content-type: application/json' \
      --url 'https://api.studio.thegraph.com/query/85556/bls_apk_registry/version/latest' \
      --data '{"query":"{ operators { id socket stake } }"}'


The list of nodes can also be quried using the following python code:

.. code-block:: python

    from pprint import pprint
    import zellular

    operators = zellular.get_operators()
    pprint(operators)

Example output:

.. code-block:: shell

    {'0x3eaa...078c': {
        'id': '0x3eaa...078c',
        'operatorId': '0xfd17...97fd',
        'pubkeyG1_X': '1313...2753',
        'pubkeyG1_Y': '1144...6864',
        'pubkeyG2_X': ['1051...8501', '1562...5720'],
        'pubkeyG2_Y': ['1601...1108', '1448...1899'],
        'public_key_g2': <eigensdk.crypto.bls.attestation.G2Point object at 0x7d8f31b167d0>,
        'socket': 'http://5.161.230.186:6001',
        'stake': 1
    }, ... }


.. note::

   The node URL of each operator can be accessed using ``operator["socket"]``.

Posting Transactions
--------------------

Zellular sequences transactions in batches. You can send a batch of transactions like this:

.. code-block:: python

    import time
    import requests
    from uuid import uuid4

    base_url = "http://5.161.230.186:6001"
    app_name = "simple_app"
    t = int(time.time())

    txs = [{"operation": "foo", "tx_id": str(uuid4()), "t": t} for _ in range(5)]
    resp = requests.put(f"{base_url}/node/{app_name}/batches", json=txs)

    print(resp.status_code)


You can add your app to zellular test network using:

.. code-block:: shell

    curl -X POST https://zellular.xyz/testnet/apps \
        -H "Content-Type: application/json" \
        -d '{"app_name": "your-app-name"}'


Fetching and Verifying Transactions
-----------------------------------

Unlike reading from a traditional blockchain, where you must trust the node you're connected to, Zellular allows trustless reading of sequenced transactions. This is achieved through an aggregated BLS signature that verifies if the sequence of transaction batches is approved by the majority of Zellular nodes. The Zellular SDK abstracts the complexities of verifying these signatures, providing a simple way to constantly pull the latest finalized transaction batches:

.. code-block:: python

    import json
    import zellular

    verifier = zellular.Verifier("simple_app", "http://5.161.230.186:6001")

    for batch, index in verifier.batches(after=0):
        txs = json.loads(batch)
        for i, tx in enumerate(txs):
            print(index, i, tx)

Example output:

.. code-block:: shell

    app: simple_app, index: 1, result: True
    app: simple_app, index: 2, result: True
    583 0 {'tx_id': '7eaa...2101', 'operation': 'foo', 't': 1725363009}
    583 1 {'tx_id': '5839...6f5e', 'operation': 'foo', 't': 1725363009}
    583 2 {'tx_id': '0a1a...05cb', 'operation': 'foo', 't': 1725363009}
    583 3 {'tx_id': '6339...cc08', 'operation': 'foo', 't': 1725363009}
    583 4 {'tx_id': 'cf4a...fc19', 'operation': 'foo', 't': 1725363009}
    ...