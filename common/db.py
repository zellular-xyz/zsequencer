import gzip
import json
import os
import threading
import time
from typing import Any, Dict, List, Optional

from config import zconfig

from . import utils


class InMemoryDB:
    _instance = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialize()
            return cls._instance

    def _initialize(self):
        self.transactions: Dict[str, Dict[str, Any]] = {}
        self.nodes_state: Dict[str, Dict[str, Any]] = {}
        self.keys: Dict[str, Any] = {}
        self.last_sequenced_tx = {}
        self.last_finalized_tx = {}
        self.load_state()

    def load_state(self) -> None:
        self.nodes_state = {}
        self.keys = self.load_keys()
        self.transactions = self.load_transactions()
        for tx in self.transactions.values():
            if tx.get("state") == "sequenced":
                if not self.last_sequenced_tx or tx.get(
                    "index", -1
                ) > self.last_sequenced_tx.get("index", "-1"):
                    self.last_sequenced_tx = tx
            elif tx.get("state") == "finalized":
                if not self.last_finalized_tx or tx.get(
                    "index", -1
                ) > self.last_finalized_tx.get("index", "-1"):
                    self.last_finalized_tx = tx

    @staticmethod
    def load_keys() -> Dict[str, Any]:
        keys_path: str = os.path.join(zconfig.SNAPSHOT_PATH, "keys.json.gz")
        try:
            with gzip.open(
                keys_path,
                "rt",
                encoding="UTF-8",
            ) as f:
                return json.load(f)
        except Exception:
            return {}

    @staticmethod
    def load_transactions(index: Optional[int] = None) -> Dict[str, Any]:
        if not index:
            snapshots: List[str] = [
                f for f in os.listdir(zconfig.SNAPSHOT_PATH) if f.endswith(".json.gz")
            ]
            index = max(
                (int(x.split(".")[0]) for x in snapshots if x.split(".")[0].isdigit()),
                default=0,
            )
        if index == 0:
            return {}
        snapshot_path = os.path.join(zconfig.SNAPSHOT_PATH, f"{index}.json.gz")
        with gzip.open(
            snapshot_path,
            "rt",
            encoding="UTF-8",
        ) as f:
            return json.load(f)

    def save_snapshot(self, index: int) -> None:
        snapshot_border = index - zconfig.SNAPSHOT_CHUNK
        remove_border = max(
            index - zconfig.SNAPSHOT_CHUNK * zconfig.REMOVE_CHUNK_BORDER, 0
        )

        snapshot_path: str = os.path.join(zconfig.SNAPSHOT_PATH, f"{index}.json.gz")
        with gzip.open(snapshot_path, "wt", encoding="UTF-8") as f:
            json.dump(
                {
                    k: v
                    for k, v in self.transactions.items()
                    if v["state"] == "finalized"
                    and snapshot_border < v.get("index", 0) <= index
                },
                f,
            )

        self.transactions = {
            k: v
            for k, v in self.transactions.items()
            if v["state"] != "finalized" or v["index"] > remove_border
        }

        keys_path: str = os.path.join(zconfig.SNAPSHOT_PATH, "keys.json.gz")
        with gzip.open(keys_path, "wt", encoding="UTF-8") as f:
            json.dump(self.keys, f)

    def get_txs(
        self, after: Optional[int] = None, states: Optional[List[str]] = None
    ) -> Dict[str, Dict[str, Any]]:
        keys = list(self.transactions.keys())

        def filter_condition(tx_hash):
            tx = self.transactions.get(tx_hash)
            if tx is None:
                return False
            if after is not None and tx.get("index", -1) <= after:
                return False
            if states and tx.get("state") not in states:
                return False
            return True

        relevant_keys = filter(filter_condition, keys)
        filtered_txs = {
            tx_hash: self.transactions[tx_hash] for tx_hash in relevant_keys
        }

        return filtered_txs

    def get_tx(
        self,
        hash: str,
    ) -> Dict[str, Any]:
        return self.transactions.get(hash, {})

    def get_not_finalized_txs(self) -> Dict[str, Any]:
        border = int(time.time()) - zconfig.FINALIZATION_TIME_BORDER

        def is_not_finalized(tx_hash):
            tx = self.transactions.get(tx_hash)
            return (
                tx
                and tx.get("state") != "finalized"
                and tx.get("insertion_timestamp", 0) < border
            )

        not_finalized_keys = filter(is_not_finalized, list(self.transactions.keys()))
        not_finalized_txs = {
            tx_hash: self.transactions[tx_hash] for tx_hash in not_finalized_keys
        }
        return not_finalized_txs

    def init_txs(self, bodies: List[str]) -> None:
        for body in bodies:
            tx_hash = utils.gen_hash(body)
            if tx_hash in self.transactions:
                continue
            self.transactions[tx_hash] = {
                "body": body,
                "hash": tx_hash,
                "state": "initialized",
            }

    def insert_sequenced_txs(self, txs: List[Dict[str, Any]]):
        last_chaining_hash: str = self.last_sequenced_tx.get("chaining_hash", "")
        index: int = self.last_sequenced_tx.get("index", 0)
        for tx in txs:
            tx_hash: str = utils.gen_hash(tx["body"])
            if tx_hash in zdb.transactions:
                continue
            index += 1
            last_chaining_hash = utils.gen_hash(last_chaining_hash + tx_hash)

            tx["index"] = index
            tx["state"] = "sequenced"
            tx["hash"] = tx_hash
            tx["chaining_hash"] = last_chaining_hash
            self.transactions[tx_hash] = tx
        self.last_sequenced_tx = tx

    def upsert_sequenced_txs(self, txs: List[Dict[str, Any]]) -> None:
        last_chaining_hash: str = self.last_sequenced_tx.get("chaining_hash", "")
        for tx in txs:
            tx_hash: str = utils.gen_hash(tx["body"])
            assert tx["hash"] == tx_hash, "invalid transaction hash"
            last_chaining_hash = utils.gen_hash(last_chaining_hash + tx["hash"])
            assert tx["chaining_hash"] == last_chaining_hash, "invalid chaining hash"
            tx["insertion_timestamp"] = int(time.time())
            self.transactions[tx_hash] = tx

            if tx["index"] > self.last_sequenced_tx.get("index", -1):
                self.last_sequenced_tx = tx

    def update_finalized_txs(self, to_: int) -> None:
        for tx_hash in list(self.transactions.keys()):
            tx = self.transactions.get(tx_hash, {})
            if tx.get("state") != "sequenced":
                continue
            if tx.get("index", float("inf")) > to_:
                continue
            tx["state"] = "finalized"
            if tx["index"] > self.last_finalized_tx.get("index", -1):
                self.last_finalized_tx = tx

            if tx["index"] % zconfig.SNAPSHOT_CHUNK == 0:
                self.save_snapshot(tx["index"])

    def update_reinitialized_txs(self, from_: int) -> None:
        timestamp = int(time.time())
        for tx_hash, tx in self.transactions.items():
            if from_ < tx.get("index", -1):
                tx.update({"state": "initialized", "insertion_timestamp": timestamp})

    def sequence_txs(self, last_finalized_tx: Dict[str, Any]) -> None:
        index = last_finalized_tx["index"]
        last_chaining_hash = last_finalized_tx["chaining_hash"]

        not_finalized_txs = [
            tx for tx in self.transactions.values() if tx.get("state") != "finalized"
        ]

        not_finalized_txs.sort(
            key=lambda x: (x.get("index") is None, x.get("index", float("inf")))
        )

        for tx in not_finalized_txs:
            index += 1
            chaining_hash = utils.gen_hash(last_chaining_hash + tx["hash"])

            tx["state"] = "sequenced"
            tx["index"] = index
            tx["chaining_hash"] = chaining_hash
            self.transactions[tx["hash"]] = tx

            last_chaining_hash = chaining_hash

    def upsert_node_state(self, node_id: str, index: int, chaining_hash: str) -> None:
        self.nodes_state[node_id] = {
            "node_id": node_id,
            "index": index,
            "chaining_hash": chaining_hash,
        }

    def get_nodes_state(self) -> List[Dict[str, Any]]:
        states = [
            state
            for state in self.nodes_state.values()
            if state.get("node_id") in zconfig.NODES
        ]
        return sorted(states, key=lambda x: x["index"], reverse=True)

    def upsert_sync_point(self, state: Dict[str, Any], sig: Any) -> None:
        self.nodes_state["sync_point"] = {
            "index": state["index"],
            "chaining_hash": state["chaining_hash"],
            "sig": json.dumps(sig),
        }

    def get_sync_point(self) -> Optional[Dict[str, Any]]:
        return self.nodes_state.get("sync_point")

    def set_keys(self, public_key, private_key) -> None:
        self.keys["zellular"] = {
            "public_key": public_key,
            "private_key": private_key,
        }

    def get_keys(self) -> Optional[Dict[str, Any]]:
        return self.keys.get("zellular")

    def delete_keys(self, public_key) -> None:
        if self.keys.get("zellular", {}).get("public_key") == public_key:
            del self.keys["zellular"]

    def set_public_shares(self, data: Dict[str, Any]) -> None:
        self.keys.setdefault("zellular", {})
        self.keys["zellular"].update(
            {
                "public_shares": data["public_shares"],
                "party": data["party"],
            }
        )

    def get_public_shares(self) -> Optional[Dict[str, Any]]:
        item = self.keys.get("zellular")
        if item and "public_shares" in item:
            return item
        return None


zdb: InMemoryDB = InMemoryDB()
