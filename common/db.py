import gzip
import hashlib
import json
import os
import threading
import time
from typing import Any, Dict, List, Optional

from config import zconfig


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
        remove_border = max(index - zconfig.SNAPSHOT_CHUNK * 2, 0)

        snapshot_path: str = os.path.join(zconfig.SNAPSHOT_PATH, f"{index}.json.gz")
        with gzip.open(snapshot_path, "wt", encoding="UTF-8") as f:
            json.dump(
                {
                    k: v
                    for k, v in self.transactions.items()
                    if snapshot_border < v.get("index", 0) <= index
                },
                f,
            )

        self.transactions = {
            k: v
            for k, v in self.transactions.items()
            if v["state"] == "initialized" or v["index"] > remove_border
        }

        keys_path: str = os.path.join(zconfig.SNAPSHOT_PATH, "keys.json.gz")
        with gzip.open(keys_path, "wt", encoding="UTF-8") as f:
            json.dump(self.keys, f)

    @staticmethod
    def gen_tx_hash(tx: Dict[str, Any]) -> str:
        tx_copy: Dict[str, Any] = {
            key: value
            for key, value in tx.items()
            if key
            not in [
                "state",
                "index",
                "chaining_hash",
                "chaining_hash_sig",
                "hash",
                "insertion_timestamp",
            ]
        }
        tx_str: str = json.dumps(tx_copy, sort_keys=True)
        tx_hash: str = hashlib.sha256(tx_str.encode()).hexdigest()
        return tx_hash

    @staticmethod
    def gen_chaining_hash(last_chaining_hash: str, tx_hash: str) -> str:
        return hashlib.sha256((last_chaining_hash + tx_hash).encode()).hexdigest()

    def get_txs(
        self,
        after: Optional[int] = None,
        states: Optional[List[str]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        filtered_txs = {}
        for tx_hash, tx in self.transactions.items():
            if after is not None and tx.get("index", -1) <= after:
                continue

            if states and tx.get("state") not in states:
                continue

            filtered_txs[tx_hash] = tx
        return filtered_txs

    def get_tx(
        self,
        hash: str,
    ) -> Dict[str, Any]:
        return self.transactions.get(hash, {})

    def get_not_finalized_txs(self) -> Dict[str, Any]:
        border: int = int(time.time()) - zconfig.FINALIZATION_TIME_BORDER
        not_finalized_txs = {}
        for tx_hash, tx in self.transactions.items():
            if (
                tx.get("state") != "finalized"
                and tx.get("insertion_timestamp", 0) < border
            ):
                not_finalized_txs[tx_hash] = tx

        return not_finalized_txs

    def insert_txs(self, txs: List[Dict[str, Any]]) -> None:
        for tx in txs:
            tx.setdefault("hash", self.gen_tx_hash(tx))
            if tx["hash"] in self.transactions:
                continue
            tx.setdefault("state", "initialized")
            self.transactions[tx["hash"]] = tx

    def upsert_sequenced_txs(self, txs: List[Dict[str, Any]]) -> None:
        last_chaining_hash: str = self.last_sequenced_tx.get("chaining_hash", "")
        for tx in txs:
            tx_hash: str = self.gen_tx_hash(tx)
            tx["state"] = "sequenced"
            tx["chaining_hash"] = self.gen_chaining_hash(last_chaining_hash, tx_hash)
            tx["insertion_timestamp"] = int(time.time())
            self.transactions[tx_hash] = tx
            last_chaining_hash = tx["chaining_hash"]
            if tx["index"] > self.last_sequenced_tx.get("index", -1):
                self.last_sequenced_tx = tx

    def update_finalized_txs(self, to_: int) -> None:
        for tx_hash, tx in self.transactions.items():
            if tx.get("state") == "sequenced" and tx.get("index", -1) <= to_:
                tx["state"] = "finalized"
                if tx["index"] > self.last_finalized_tx.get("index", -1):
                    self.last_finalized_tx = tx

                if tx["index"] % zconfig.SNAPSHOT_CHUNK == 0:
                    # TODO: Should transfer to the node code
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
            chaining_hash = self.gen_chaining_hash(last_chaining_hash, tx["hash"])

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
