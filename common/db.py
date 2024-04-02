import hashlib
import json
import threading
import time
from typing import Any, Dict, List, Optional

import pymongo
from pymongo.cursor import Cursor
from pymongo.database import Database

import config


class DatabaseClient:
    _instance = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(DatabaseClient, cls).__new__(cls)
                cls._instance._initialize()
            return cls._instance

    def _initialize(self):
        self.client = pymongo.MongoClient("mongodb://localhost:27017/")
        self.database: Database = self.client[config.DB_NAME]

    def get_database(self) -> Database:
        return self.database


class CollectionManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(CollectionManager, cls).__new__(cls)
                cls._instance._initialize()
            return cls._instance

    def _initialize(self):
        self.txs_coll = TxsColl()
        self.nodes_state_coll = NodesStateColl()
        self.keys_coll = keysColl()

    @property
    def txs(self):
        return self.txs_coll

    @property
    def nodes_state(self):
        return self.nodes_state_coll

    @property
    def keys(self):
        return self.keys_coll


class TxsColl:
    _lock: threading.Lock = threading.Lock()

    def __init__(self):
        db_client: DatabaseClient = DatabaseClient()
        db: Database = db_client.get_database()
        self.coll = db.get_collection("transactions")
        # TODO: transfer to the init db script in production
        self.coll.create_index([("hash", pymongo.ASCENDING)], unique=True)

    @staticmethod
    def gen_tx_hash(tx: Dict[str, Any]) -> str:
        tx_copy: Dict[str, Any] = {
            key: value
            for key, value in tx.items()
            if key
            not in [
                "_id",
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
        search_term: Optional[Any] = None,
    ) -> Dict[str, Any]:
        query: Dict[str, Any] = {}

        if after is not None:
            query["index"] = {"$gt": after}

        if states:
            query["state"] = {"$in": states}

        if search_term:
            if isinstance(search_term, int) or str(search_term).isdigit():
                search_term = int(search_term)
            query["$or"] = [
                {"id": search_term},
                {"index": search_term},
                {"hash": search_term},
                {"chaining_hash": search_term},
            ]
        cursor: Cursor = self.coll.find(query, {"_id": 0})
        return {tx["hash"]: tx for tx in cursor}

    def get_not_finalized_txs(self) -> Dict[str, Any]:
        border: int = int(time.time()) - config.FINALIZATION_TIME_BORDER
        cursor: Cursor = self.coll.find(
            {"state": {"$ne": "finalized"}, "insertion_timestamp": {"$lt": border}},
            {"_id": 0},
        )
        return {tx["hash"]: tx for tx in cursor}

    def get_last_tx_by_state(self, state: str) -> Optional[Dict[str, Any]]:
        return self.coll.find_one(
            {"state": state}, sort=[("index", -1)], projection={"_id": 0}
        )

    def insert_tx(self, tx: Dict[str, Any]) -> bool:
        try:
            tx["hash"] = self.gen_tx_hash(tx)
            tx["state"] = "initialized"
            self.coll.insert_one(tx)
            return True
        except Exception:
            return False

    def upsert_sequenced_txs(self, txs: List[Dict[str, Any]]) -> None:
        batch: List[Any] = []
        last_synced_tx: Dict[str, Any] = self.get_last_tx_by_state("sequenced") or {}
        last_chaining_hash: str = last_synced_tx.get("chaining_hash", "")
        for tx in txs:
            tx_hash: str = self.gen_tx_hash(tx)
            tx["state"] = "sequenced"
            tx["chaining_hash"] = self.gen_chaining_hash(last_chaining_hash, tx_hash)
            batch.append(
                pymongo.UpdateOne({"hash": tx_hash}, {"$set": tx}, upsert=True)
            )
            last_chaining_hash = tx["chaining_hash"]
        if batch:
            self.coll.bulk_write(batch)

    def update_finalized_txs(self, to_: int) -> None:
        # TODO: if _to is greater than the last sequenced tx index should sync with the sequencer
        self.coll.update_many(
            {"state": "sequenced", "index": {"$lte": to_}},
            {"$set": {"state": "finalized"}},
        )

    def update_reinitialized_txs(self, from_: int) -> None:
        timestamp = int(time.time())
        self.coll.update_many(
            {"index": {"$gt": from_}},
            {"$set": {"state": "initialized", "insertion_timestamp": timestamp}},
        )

    def sequence_txs(self, last_finalized_tx: Dict[str, Any]) -> None:
        index: int = last_finalized_tx["index"]
        last_chaining_hash: str = last_finalized_tx["chaining_hash"]
        cursor: Cursor = self.coll.find({"state": {"$ne": "finalized"}}).sort(
            [("index", 1), ("index", -1)]
        )
        for tx in cursor:
            index += 1
            chaining_hash: str = self.gen_chaining_hash(last_chaining_hash, tx["hash"])
            self.coll.update_one(
                {"hash": tx["hash"]},
                {
                    "$set": {
                        "state": "sequenced",
                        "index": index,
                        "chaining_hash": chaining_hash,
                    }
                },
            )

            last_chaining_hash = chaining_hash


class NodesStateColl:
    _lock: threading.Lock = threading.Lock()

    def __init__(self):
        db_client: DatabaseClient = DatabaseClient()
        db: Database = db_client.get_database()
        self.coll = db.get_collection("nodes_state")

    def upsert_node_state(self, node_id: str, index: int, chaining_hash: str) -> None:
        self.coll.update_one(
            {"node_id": node_id},
            {"$set": {"index": index, "chaining_hash": chaining_hash}},
            upsert=True,
        )

    def get_nodes_state(self) -> List[Dict[str, Any]]:
        return list(
            self.coll.find(
                {"node_id": {"$in": list(config.NODES.keys())}}, {"_id": 0}
            ).sort("index", pymongo.DESCENDING)
        )

    def upsert_sync_point(self, state: Dict[str, Any], sig: Any) -> None:
        self.coll.update_one(
            {"_id": "sync_point"},
            {
                "$set": {
                    "index": state["index"],
                    "chaining_hash": state["chaining_hash"],
                    "sig": json.dumps(sig),
                }
            },
            upsert=True,
        )

    def get_sync_point(self) -> Optional[Dict[str, Any]]:
        return self.coll.find_one({"_id": "sync_point"}, {"_id": 0})


class keysColl:
    _lock: threading.Lock = threading.Lock()

    def __init__(self):
        db_client: DatabaseClient = DatabaseClient()
        db: Database = db_client.get_database()
        self.coll = db.get_collection("keys")

    def set(self, public_key, private_key) -> None:
        self.coll.insert_one(
            {
                "_id": "zellular",
                "public_key": public_key,
                "private_key": private_key,
            }
        )

    def get(self) -> Optional[Dict[str, Any]]:
        return self.coll.find_one({"_id": "zellular"})

    def delete(self, public_key) -> None:
        self.coll.delete_one(
            {
                "public_key": public_key,
            }
        )

    def set_public_shares(self, data: Dict[str, Any]) -> None:
        self.coll.update_one(
            {"_id": "zellular"},
            {
                "$set": {
                    "public_shares": json.dumps(data["public_shares"]),
                    "party": data["party"],
                }
            },
            upsert=True,
        )

    def get_public_shares(self) -> Optional[Dict[str, Any]]:
        return self.coll.find_one(
            {"_id": "zellular", "public_shares": {"$exists": True}}
        )
