# Run Nodes Locally

## Run Nodes script

- Check examples directory on the root ``` examples ```. This directory contains runner script which has this responsibility to launch different nodes and a sequencer.


- For the sake of simplicity, This script makes different bash script files to launch nodes and sequencer tasks. 


- You should install these packages to run nodes network on macos:
``` brew install python3 cmake gcc gmp ```.



- After installation of necessary packages, you can find ```generate_nodes_command``` python script in examples directory.
This script creates separated bash script files which will launch different node workers listening on specified socker ports.
By running these script files, you actually have your network. Note that the node with minimum node-id will be the initial leader of the network.

- ``` ./node_1.sh && ./node_2.sh && ./node_3.sh ... ``` , also you can run these bash files on different terminals.

- Now you have successfully set up your network, it is time to run a simulation on the network. For this purpose, you can find nodes_network_simulation python script in examples directory.
This script sends different batches of random messages to nodes on the network and tries to act as a client on this network.
you can check the logs of different network to observe communication process between nodes to commit transactions.