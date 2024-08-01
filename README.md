# Zellular Sequencer

<b> Do not use it in Production, testnet only. </b>

A PoC implementation of the [Zellular BFT Protocol](https://docs.zellular.xyz/protocol.html) in Python.

## Run

### EigenLayer CLI Installation

Follow the instructions at this [link](https://docs.eigenlayer.xyz/eigenlayer/operator-guides/operator-installation#install-cli-using-binary) to install the `EigenLayer CLI` and generate the `BLS` and `ECDSA` key files for your node.

After installation, use the following commands to create your key files:
```bash
eigenlayer operator keys create --key-type ecdsa key1
eigenlayer operator keys create --key-type bls key2
```
Replace `key1` and `key2` with your desired key names. These commands will generate key files in the `~/.eigenlayer/operator_keys` directory with filenames `key1.ecdsa.key.json` and `key2.bls.key.json`.

### Setup Environment
To configure your node environment:

1. Create a sample environment file:
    ```bash
    cp .env.example .env
    ```
2. Modify the .env file with the appropriate parameters:
    ```
    ZSEQUENCER_BLS_KEY_FILE=~/.eigenlayer/operator_keys/key1.ecdsa.key.json
    ZSEQUENCER_BLS_KEY_PASSWORD=[your password for ecdsa key file]
    ZSEQUENCER_ECDSA_KEY_FILE=~/.eigenlayer/operator_keys/key2.bls.key.json
    ZSEQUENCER_ECDSA_KEY_PASSWORD=[your password for bls key file]
    ZSEQUENCER_NODES_FILE=./nodes.json
    ZSEQUENCER_APPS_FILE=./apps.json
    ZSEQUENCER_SNAPSHOT_PATH=/tmp/zellular_dev_net/db_1
    ZSEQUENCER_PORT=6001
    ZSEQUENCER_SNAPSHOT_CHUNK=1000000
    ZSEQUENCER_REMOVE_CHUNK_BORDER=3
    ZSEQUENCER_THRESHOLD_PERCENT=67
    ZSEQUENCER_SEND_TXS_INTERVAL=0.01
    ZSEQUENCER_SYNC_INTERVAL=0.01
    ZSEQUENCER_FINALIZATION_TIME_BORDER=120
    ZSEQUENCER_SIGNATURES_AGGREGATION_TIMEOUT=5
    ```
    - `ZSEQUENCER_PORT`: Set the node port.
    - `ZSEQUENCER_SNAPSHOT_CHUNK`: Set the maximum number of finalized transactions to store in a file.
    - `ZSEQUENCER_REMOVE_CHUNK_BORDER`: Determines when old transactions are removed from memory. The node automatically removes old transactions from database and store it in a file, when the index of last finalized transactions exceed from `ZSEQUENCER_REMOVE_CHUNK_BORDER`*`ZSEQUENCER_SNAPSHOT_CHUNK`
    - `ZSEQUENCER_SEND_TXS_INTERVAL`: Interval (in seconds) for sending transaction requests.
    - `ZSEQUENCER_SYNC_INTERVAL`: Synchronization interval (in seconds) for fetching locked and finalized sync points if available.
    - `ZSEQUENCER_FINALIZATION_TIME_BORDER`: Timeout for finalizing transactions.
    - `ZSEQUENCER_SIGNATURES_AGGREGATION_TIMEOUT`: Timeout for gathering threshold signatures.
3. Obtain node and app data from your network administrator and store it in nodes.json and apps.json files:
    ```
    ZSEQUENCER_NODES_FILE=./nodes.json
    ZSEQUENCER_APPS_FILE=./apps.json
    ```

### Run With Docker: 
- After setting up your environment, use the following command to start your node:

```bash
docker compose up -d
```




### Setup Manually:

#### Dependencies

- Python 3
- CMake
- g++
- To install the dependencies for the `eigen-sdk` Python package, follow the guide provided at this [link](https://github.com/zellular-xyz/eigensdk-python?tab=readme-ov-file#dependencies). 

- For the `Zdellular Sequencer` package, use the following commands:
    ```bash
    wget https://github.com/zellular-xyz/zsequencer/archive/refs/tags/latest.zip
    unzip latest.zip
    cd zsequencer-latest
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    ```

#### Run the node:
- After setting up the environment and installing dependencies, start the node with this command:
```bash
python run.py
```

## Testing

### General Test

To run a test network with 3 nodes, each having a stake value of 10, where confirmation from a threshold percentage of the total stake is sufficient to finalize transactions, and to send 100,000 transactions for sequencing, use the following command:

```bash
python examples/runner.py --test general
```

You can adjust the batch size and number of simulated transactions in the `examples/general_test.py` file. To modify parameters such as the number of nodes, stake value, threshold percentage, and number of transactions, edit the `examples/runner.py` file.

### Throughput Test

To conduct a throughput test, use the following command:
```bash
python examples/runner.py --test throughput
```

This command will run a 3-node test network for throughput evaluation. Parameters related to this test, such as latency and initial rate, can be adjusted in the `examples/throughput_test.py` file. As with the general test, you can modify node parameters in the `examples/runner.py` file.

Like the last test, You can modify the node parameters in the `examples/runner.py` file.

