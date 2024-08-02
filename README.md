# Zellular Sequencer

<b> Do not use it in Production, testnet only. </b>

A PoC implementation of the [Zellular BFT Protocol](https://docs.zellular.xyz/protocol.html) in Python.

## Run

### Generate Keys

- Follow [these instructions](https://docs.eigenlayer.xyz/eigenlayer/operator-guides/operator-installation#install-cli-using-binary) to install the `eigenlayer` CLI.
- Use the following commands to generate the `BLS` and `ECDSA` key files for your node:
```bash
eigenlayer operator keys create --key-type ecdsa key1
eigenlayer operator keys create --key-type bls key2
```
Replace `key1` and `key2` with your desired key names. These commands will generate key files in the `~/.eigenlayer/operator_keys` directory with filenames `key1.ecdsa.key.json` and `key2.bls.key.json`.

### Setup Environment

- Create an environment file based on the example:
    ```bash
    cp .env.example .env
    ```
- Modify the .env file with the appropriate parameters:
    ```
    ZSEQUENCER_BLS_KEY_FILE=~/.eigenlayer/operator_keys/key1.ecdsa.key.json
    ZSEQUENCER_BLS_KEY_PASSWORD=[your password for ecdsa key file]
    ZSEQUENCER_ECDSA_KEY_FILE=~/.eigenlayer/operator_keys/key2.bls.key.json
    ZSEQUENCER_ECDSA_KEY_PASSWORD=[your password for bls key file]
    ZSEQUENCER_NODES_FILE=./nodes.json
    ZSEQUENCER_APPS_FILE=./apps.json
    ZSEQUENCER_SNAPSHOT_PATH=./db
    ZSEQUENCER_PORT=6001
    ZSEQUENCER_SNAPSHOT_CHUNK=1000000
    ZSEQUENCER_REMOVE_CHUNK_BORDER=3
    ZSEQUENCER_THRESHOLD_PERCENT=67
    ZSEQUENCER_SEND_TXS_INTERVAL=0.01
    ZSEQUENCER_SYNC_INTERVAL=0.01
    ZSEQUENCER_FINALIZATION_TIME_BORDER=120
    ZSEQUENCER_SIGNATURES_AGGREGATION_TIMEOUT=5
    ```
    - `ZSEQUENCER_PORT`: The port the node receives requests on
    - `ZSEQUENCER_SNAPSHOT_CHUNK`: The number of finalized transactions that are archived in each file
    - `ZSEQUENCER_REMOVE_CHUNK_BORDER`: The border that transactions older that will be archived
    - `ZSEQUENCER_SEND_TXS_INTERVAL`: Interval (in seconds) for sending transaction requests from node to the sequencer
    - `ZSEQUENCER_SYNC_INTERVAL`: Interval (in seconds) for the sequencer to fetch locked and finalized signatures from nodes
    - `ZSEQUENCER_FINALIZATION_TIME_BORDER`: The border that nodes dispute against the sequencer if it fails to update the finalization proof before that
    - `ZSEQUENCER_SIGNATURES_AGGREGATION_TIMEOUT`: Timeout for gathering signatures from nodes
- Get the nodes and apps data from your network administrator and store it in the nodes.json and apps.json files:
    ```
    ZSEQUENCER_NODES_FILE=./nodes.json
    ZSEQUENCER_APPS_FILE=./apps.json
    ```

### Run using docker: 

```bash
docker compose up -d
```

### Run using source:

#### Dependencies

- Python3, CMake, g++, MCL (installation guide)(https://github.com/zellular-xyz/eigensdk-python?tab=readme-ov-file#dependencies) to install MCL required for generating BLS signatures. 

#### Install
```bash
wget https://github.com/zellular-xyz/zsequencer/archive/refs/tags/latest.zip
unzip latest.zip
cd zsequencer-latest
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

#### Run
Use the following command after creating the .env file as explained above:

```bash
python run.py
```

## Testing

The following example runs a local network with 3 nodes and sends 100,000 transactions for sequencing:

```bash
python examples/runner.py --test general
```
To modify parameters such as the number of nodes, their stake, confirmation threshold percentage, the number of transactions, etc edit the `examples/runner.py` file.
