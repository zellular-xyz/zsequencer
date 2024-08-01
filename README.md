# Zellular Sequencer

<b> Do not use it in Production, testnet only. </b>

A PoC implementation of the [Zellular BFT Protocol](https://docs.zellular.xyz/protocol.html) in Python.

## Install

### Dependencies
- Python 3

```
wget https://github.com/zellular-xyz/zsequencer/archive/refs/tags/latest.zip
unzip latest.zip
cd zsequencer-latest
pip install .
```

## Test

Use the following command to run a test network with 3 nodes where confirmation from 2 is enough to finalize txs and send 100k txs to be sequenced:

```
python examples/runner.py --test general
```
The number of nodes, threshold, number of txs and other parameters can be adjusted by editing the `examples/runner.py`
