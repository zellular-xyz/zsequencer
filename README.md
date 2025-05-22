# Zellular Sequencer

> **Warning:** Do not use in Production, testnet only.

A PoC implementation of the [Zellular BFT Protocol](https://docs.zellular.xyz/protocol.html) in Python.

## Table of Contents

- [Requirements](#requirements)
- [Documentation](#documentation)
- [Joining EigenLayer Test Network](#joining-eigenlayer-test-network)
- [Testing](#testing)

## Requirements

- Docker and Docker Compose
- Python 3.10+ (for development and testing)
- EigenLayer CLI (for key generation)

## Documentation

Comprehensive documentation is available at [docs.zellular.xyz](https://docs.zellular.xyz/), including:

- [Architecture Overview](https://docs.zellular.xyz/architecture.html) - Learn about the system design
- [Protocol Specification](https://docs.zellular.xyz/protocol.html) - Detailed explanation of the BFT protocol
- [SDK Documentation](https://docs.zellular.xyz/sdk.html) - How to build applications with Zellular
- [Example Applications](https://docs.zellular.xyz/examples/token.html) - Sample implementations including:
  - [Token Service](https://docs.zellular.xyz/examples/token.html)
  - [Orderbook](https://docs.zellular.xyz/examples/orderbook.html)
  - [Verification](https://docs.zellular.xyz/examples/verification.html)
  - [Downtime Monitoring](https://docs.zellular.xyz/examples/downtime_monitoring.html)

## Joining EigenLayer Test Network

### Recommended Node Specifications

For running a Zellular Sequencer node, the [General Purpose - large](https://docs.eigenlayer.xyz/eigenlayer/operator-guides/eigenlayer-node-classes#general-purpose-eigenlayer-node-classes) with 2 vCPUs, 8 GB RAM, and 5 Mbps network bandwidth is sufficient.

### Install Docker

Follow [these instructions](https://docs.docker.com/engine/install/#server) to install the latest version of Docker.

### Generate Keys

Follow [these instructions](https://docs.eigenlayer.xyz/eigenlayer/operator-guides/operator-installation#install-cli-using-binary) to install the `eigenlayer` CLI to generate the `BLS` and `ECDSA` key files for your node:

```bash
eigenlayer operator keys create --key-type ecdsa zellular
eigenlayer operator keys create --key-type bls zellular
```

### Register the Operator

Follow the [EigenLayer Operator Guide](https://docs.eigenlayer.xyz/eigenlayer/operator-guides/operator-installation#fund-ecdsa-wallet) to fund your ECDSA wallet and register as an operator on EigenLayer core contracts.

Zellular Holesky testnet operators need at least 1 Lido Staked Ether (stETH) delegated to them:

1. Obtain Holesky testnet ethers from the [available faucets](https://docs.eigenlayer.xyz/eigenlayer/restaking-guides/restaking-user-guide/testnet/obtaining-testnet-eth-and-liquid-staking-tokens-lsts#obtain-holesky-eth-aka-holeth-via-a-faucet)
2. Use the [Lido testnet staking dashboard](https://stake-holesky.testnet.fi/) to stake these ethers and receive Lido staking tokens
3. Restake these tokens on the [EigenLayer Holesky dashboard](https://holesky.eigenlayer.xyz/restake/stETH) and delegate them to your operator

### Set Up Your Node

1. Create a directory for your node:
   ```bash
   mkdir zsequencer
   cd zsequencer
   ```

2. Download the docker-compose file:
   ```bash
   curl -o docker-compose.yml https://raw.githubusercontent.com/zellular-xyz/zsequencer/refs/heads/main/docker-compose-pull.yml
   ```

3. Download the environment file template:
   ```bash
   curl -o .env https://raw.githubusercontent.com/zellular-xyz/zsequencer/refs/heads/main/.env.example
   ```

4. Edit the `.env` file with your configuration:
   ```
   ZSEQUENCER_BLS_KEY_FILE=~/.eigenlayer/operator_keys/zellular.bls.key.json
   ZSEQUENCER_BLS_KEY_PASSWORD=[your password for bls key file]
   ZSEQUENCER_ECDSA_KEY_FILE=~/.eigenlayer/operator_keys/zellular.ecdsa.key.json
   ZSEQUENCER_ECDSA_KEY_PASSWORD=[your password for ecdsa key file]
   ZSEQUENCER_REGISTER_SOCKET=[htttp://server-ip:port]
   ```

   > **Note**: The only required variables to set are:
   > - Path to BLS & ECDSA key files and their passwords
   > - Socket URL for registering the operator with Zellular AVS on EigenLayer

### Run the Node

1. Create the Docker network (first time only):
   ```bash
   docker network create zsequencer_net
   ```

2. Start your node:
   ```bash
   docker compose up -d
   ```

## Testing

### End-to-End (E2E) Tests

The project includes end-to-end tests that simulate a network of nodes and allow you to test functionality in a controlled environment.

#### Prerequisites

- Docker and Docker Compose installed
- Python with `uv` package manager

#### Steps to Run E2E Tests

1. Build the Docker container:
   ```bash
   docker compose build
   ```

2. Navigate to the E2E test directory:
   ```bash
   cd tests/e2e
   ```

3. Run the network simulation:
   ```bash
   uv run network_runner.py start --config sample-config.json
   ```
   This will start a network of nodes based on the configuration in `sample-config.json`.

4. In a separate terminal, run the client to interact with the network:
   ```bash
   cd tests/e2e
   uv run client.py
   ```
   The client will send example transactions to the nodes in the network.

5. To view logs from all containers:
   ```bash
   # Opens a terminal window for each container showing its logs
   uv run network_runner.py logs --terminal=gnome-terminal
   ```
   Supported terminals: gnome-terminal, xterm, konsole, terminator, tilix

   For individual container logs, use the docker logs command directly:
   ```bash
   docker logs -f zsequencer-node-0
   ```

6. When you're done testing, you can stop all the containers:
   ```bash
   uv run network_runner.py stop
   ```
   This will stop and remove all zsequencer node containers that were started.

#### Configuration Options

The sample configuration file (`sample-config.json`) lets you control:
- Number of nodes in the network
- Base port for the nodes
- Environment variables for all nodes
- Simulated network conditions, including outages and delays
