import hashlib
import json

from pyfrost.network_http.abstract import DataManager
from pyfrost.network_http.abstract import NodesInfo as BaseNodeInfo
from pyfrost.network_http.abstract import Validators
from pyfrost.network_http.node import Node
from pyfrost.network_http.sa import SA

import config

from ..common import db

dk_private_key = None
nonces = {}


class NodeDataManager(DataManager):
    def __init__(self):
        super().__init__()
        self.__nonces = {}

    def set_nonce(self, nonce_public, nonce_private):
        self.__nonces[nonce_public] = nonce_private

    def get_nonce(self, nonce_public):
        return self.__nonces[nonce_public]

    def remove_nonce(self, nonce_public):
        del self.__nonces[nonce_public]

    def set_key(self, key, value):
        db.distributed_keys.insert_one(
            {
                "_id": "zellular",
                "public_key": str(key),
                "private_key": json.dumps(value),
            }
        )

    def get_key(self, key):
        global dk_private_key
        if not dk_private_key:
            dkg_record = db.distributed_keys.find_one({"public_key": key}) or {}
            dk_private_key = json.loads(dkg_record.get("private_key"))
        return dk_private_key

    def remove_key(self, key):
        db.distributed_keys.delete_one({"public_key": str(key)})


class NodeValidators(Validators):
    def __init__(self):
        super().__init__()

    @staticmethod
    def caller_validator(sender_ip, method):
        if not db.distributed_keys.find_one({"_id": "zellular"}):
            allowed_methods = ["/v1/dkg/round1", "/v1/dkg/round2", "/v1/dkg/round3"]
        else:
            allowed_methods = ["/v1/sign", "/v1/generate-nonces"]
        if sender_ip == config.SEQUENCER["host"] and method in allowed_methods:
            return True
        return False

    @staticmethod
    def data_validator(input_data):
        # tx = db.get_tx(input_data['index'])
        # if tx['chaining_hash'] != input_data['chaining_hash']:
        #     raise ValueError(
        #         "Input data is not valid: chaining_hash mismatch")

        result = {"data": input_data}
        hash_obj = hashlib.sha3_256(json.dumps(result["data"]).encode())
        hash_hex = hash_obj.hexdigest()
        result["hash"] = hash_hex
        return result


class NodesInfo(BaseNodeInfo):
    def __init__(self):
        self.nodes = config.NODES

    def lookup_node(self, node_id: str = None):
        return self.nodes.get(node_id, {})

    def get_all_nodes(self, n=None):
        if n is None:
            n = len(self.nodes)
        return list(self.nodes.keys())[:n]


async def request_nonces():
    global nonces
    if not db.distributed_keys.find_one({"_id": "zellular"}):
        return

    node_ids = [
        n["id"]
        for n in config.NODES.values()
        if len(nonces.get(n["id"], [])) < config.MIN_NONCES
    ]
    if not node_ids:
        return

    nodes_info = NodesInfo()
    sa = SA(nodes_info, default_timeout=50)
    nonces_response = await sa.request_nonces(node_ids, config.MIN_NONCES * 10)
    for node_id in node_ids:
        nonces.setdefault(node_id, [])
        nonces[node_id] += nonces_response[node_id]["data"]


async def request_sig(data, party):
    dk = db.distributed_keys.find_one({"_id": "zellular"}, {"_id": 0, "private_key": 0})
    if not dk:
        return

    nonces_dict = {}
    for node_id in party[:]:
        if not nonces.get(node_id):
            party.remove(node_id)
            continue
        nonces_dict[node_id] = nonces[node_id].pop()

    if len(party) < config.THRESHOLD_NUMBER:
        await request_nonces()
        return

    nodes_info = NodesInfo()
    sa = SA(nodes_info, default_timeout=50)
    sa_data = {"data": data}
    dk["public_key"] = int(dk["public_key"])
    dk["public_shares"] = json.loads(dk["public_shares"])
    dk["party"] = party

    signature = await sa.request_signature(dk, nonces_dict, sa_data, party)
    return signature


def run(node_number):
    data_manager = NodeDataManager()
    nodes_info = NodesInfo()
    node = Node(
        data_manager,
        str(node_number),
        config.NODE["private_key"],
        nodes_info,
        NodeValidators.caller_validator,
        NodeValidators.data_validator,
    )
    node.run_app()
