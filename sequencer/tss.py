import hashlib
import json
from typing import Any, Dict, List, Optional

from pyfrost.network_http.abstract import DataManager
from pyfrost.network_http.abstract import NodesInfo as BaseNodeInfo
from pyfrost.network_http.abstract import Validators
from pyfrost.network_http.node import Node
from pyfrost.network_http.sa import SA

import config

from ..common import db

cm: db.CollectionManager = db.CollectionManager()
g_private_key: Dict[str, Any] = {}
nonces: Dict[str, Any] = {}


class NodeDataManager(DataManager):
    def __init__(self):
        super().__init__()
        self.__nonces = {}

    def set_nonce(self, nonce_public: str, nonce_private: str) -> None:
        self.__nonces[nonce_public] = nonce_private

    def get_nonce(self, nonce_public: str) -> str:
        return self.__nonces[nonce_public]

    def remove_nonce(self, nonce_public: str) -> None:
        del self.__nonces[nonce_public]

    def set_key(self, key: int, value: Dict[str, Any]) -> None:
        cm.keys.set(public_key=str(key), private_key=json.dumps(value))

    def get_key(self, key: int) -> Optional[Dict[str, Any]]:
        global g_private_key
        if not g_private_key:
            keys: Optional[Dict[str, Any]] = cm.keys.get()
            if not keys:
                return
            g_private_key = json.loads(keys.get("private_key", "{}"))
        return g_private_key

    def remove_key(self, key: int) -> None:
        cm.keys.delete(public_key=str(key))


class NodeValidators(Validators):
    def __init__(self):
        super().__init__()

    @staticmethod
    def caller_validator(sender_ip: str, method: str) -> bool:
        if not cm.keys.get():
            allowed_methods = ["/v1/dkg/round1", "/v1/dkg/round2", "/v1/dkg/round3"]
        else:
            allowed_methods = ["/v1/sign", "/v1/generate-nonces"]
        if sender_ip == config.SEQUENCER["host"] and method in allowed_methods:
            return True
        return False

    @staticmethod
    def data_validator(input_data: Dict[str, Any]):
        # tx = db.get_tx(input_data['index'])
        # if tx['chaining_hash'] != input_data['chaining_hash']:
        #     raise ValueError(
        #         "Input data is not valid: chaining_hash mismatch")

        result: Dict[str, Any] = {"data": input_data}
        hash_obj = hashlib.sha3_256(json.dumps(result["data"]).encode())
        hash_hex: str = hash_obj.hexdigest()
        result["hash"] = hash_hex
        return result


class NodesInfo(BaseNodeInfo):
    def __init__(self):
        self.nodes: Dict[str, Any] = config.NODES

    def lookup_node(self, node_id: str) -> Dict[str, Any]:
        return self.nodes.get(node_id) or {}

    def get_all_nodes(self, n: Optional[int] = None) -> List[str]:
        if n is None:
            n = len(self.nodes)
        return list(self.nodes.keys())[:n]


async def request_nonces() -> None:
    global nonces
    if not cm.keys.get_public_shares():
        return

    node_ids: List[str] = [
        n["id"]
        for n in config.NODES.values()
        if len(nonces.get(n["id"], [])) < config.MIN_NONCES
    ]
    if not node_ids:
        return

    nodes_info: NodesInfo = NodesInfo()
    sa: SA = SA(nodes_info, default_timeout=50)
    nonces_response: Dict[str, Any] = await sa.request_nonces(
        node_ids, config.MIN_NONCES * 10
    )
    for node_id in node_ids:
        nonces.setdefault(node_id, [])
        nonces[node_id] += nonces_response[node_id]["data"]


async def request_sig(
    data: Dict[str, Any], party: List[str]
) -> Optional[Dict[str, Any]]:
    keys: Optional[Dict[str, Any]] = cm.keys.get_public_shares()
    if not keys:
        return

    nonces_dict: Dict[str, Any] = {}
    for node_id in party[:]:
        if not nonces.get(node_id):
            party.remove(node_id)
            continue
        nonces_dict[node_id] = nonces[node_id].pop()

    if len(party) < config.THRESHOLD_NUMBER:
        await request_nonces()
        return

    nodes_info: NodesInfo = NodesInfo()
    sa: SA = SA(nodes_info, default_timeout=50)
    sa_data: Dict[str, Any] = {"data": data}
    keys["public_key"] = int(keys["public_key"])
    keys["public_shares"] = json.loads(keys["public_shares"])
    keys["party"] = party

    signature = await sa.request_signature(keys, nonces_dict, sa_data, party)
    return signature


def run(node_number):
    data_manager: NodeDataManager = NodeDataManager()
    nodes_info: NodesInfo = NodesInfo()
    node: Node = Node(
        data_manager,
        str(node_number),
        config.NODE["private_key"],
        nodes_info,
        NodeValidators.caller_validator,
        NodeValidators.data_validator,
    )
    node.run_app()
