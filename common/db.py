import hashlib
import json
import threading
import time
from typing import Any, Dict, List, Optional

import pymongo
from pymongo.collection import Collection
from pymongo.cursor import Cursor
from pymongo.database import Database

import config

client: pymongo.MongoClient = pymongo.MongoClient("mongodb://localhost:27017/")
database: Database = client[config.DB_NAME]
nodes_states_col: Collection = database["nodes_states"]
distributed_keys: Collection = database["distributed_keys"]
txs_col: Collection = database["txs"]

insertion_lock: threading.Lock = threading.Lock()


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


def get_not_finalized_txs() -> Dict[str, Any]:
    border: int = int(time.time()) - config.FINALIZATION_TIME_BORDER
    cursor: Cursor = txs_col.find(
        {"state": {"$ne": "finalized"}, "insertion_timestamp": {"$lt": border}},
        {"_id": 0},
    )
    return {tx["hash"]: tx for tx in cursor}


def get_tx(search_term: Any) -> Optional[Dict[str, Any]]:
    if search_term == "last":
        pass

    if isinstance(search_term, int) or search_term.isdigit():
        search_term = int(search_term)

    return txs_col.find_one(
        {
            "$or": [
                {"id": search_term},
                {"index": search_term},
                {"hash": search_term},
                {"chaining_hash": search_term},
            ]
        },
        {"_id": 0},
    )


def get_initialized_txs() -> Dict[str, Any]:
    cursor: Cursor = txs_col.find(
        {"state": "initialized"},
        {"_id": 0},
    )
    return {tx["hash"]: tx for tx in cursor}


def get_txs(
    after: int = 0, states: List[str] = ["initialized", "sequenced", "finalized"]
) -> List[Dict[str, Any]]:
    return list(
        txs_col.find(
            {"state": {"$in": states}, "index": {"$gt": after}},
            {"_id": 0, "state": 0, "hash": 0, "chaining_hash": 0},
        )
    )


def get_last_synced_tx() -> Optional[Dict[str, Any]]:
    return txs_col.find_one(
        {"state": {"$in": ["sequenced", "finalized"]}}, sort=[("index", -1)]
    )


def get_last_tx(state: str) -> Dict[str, Any]:
    return txs_col.find_one({"state": state}, sort=[("index", -1)]) or {}


def update_finalized_txs(_to: int) -> None:
    txs_col.update_many(
        {"state": "sequenced", "index": {"$lte": _to}},
        {"$set": {"state": "finalized"}},
    )


def get_sync_point() -> Optional[Dict[str, Any]]:
    return nodes_states_col.find_one({"_id": "sync_point"}, {"_id": 0})


def upsert_sequenced_txs(txs: List[Dict[str, Any]]) -> None:
    batch: List[Any] = []
    last_synced_tx: Dict[str, Any] = get_last_synced_tx() or {}
    last_chaining_hash: str = last_synced_tx.get("chaining_hash", "")
    for tx in txs:
        tx_hash: str = gen_tx_hash(tx)
        tx["state"] = "sequenced"
        tx["chaining_hash"] = hashlib.sha256(
            (last_chaining_hash + tx_hash).encode()
        ).hexdigest()
        batch.append(pymongo.UpdateOne({"hash": tx_hash}, {"$set": tx}, upsert=True))
        last_chaining_hash = tx["chaining_hash"]
    if batch:
        txs_col.bulk_write(batch)


def upsert_node_state(node_id: str, index: int, chaining_hash: str) -> None:
    nodes_states_col.update_one(
        {"node_id": node_id},
        {"$set": {"index": index, "chaining_hash": chaining_hash}},
        upsert=True,
    )


def get_nodes_state() -> List[Dict[str, Any]]:
    return list(
        nodes_states_col.find(
            {"node_id": {"$in": list(config.NODES.keys())}}, {"_id": 0}
        ).sort("index", pymongo.DESCENDING)
    )


def insert_tx(tx: Dict[str, Any]) -> bool:
    tx["hash"] = gen_tx_hash(tx)
    tx["state"] = "initialized"
    existing_doc: Optional[Dict[str, Any]] = txs_col.find_one({"hash": tx["hash"]})
    if existing_doc is None:
        txs_col.insert_one(tx)
        return True
    else:
        return False


def insert_txs(txs: List[Dict[str, Any]]) -> None:
    bulk_operations: List[Any] = []

    existing_hashes: set = set(tx["hash"] for tx in txs_col.find({}, {"hash": 1}))

    last_tx: Dict[str, Any] = txs_col.find_one(sort=[("index", -1)]) or {}
    last_chaining_hash: str = last_tx.get("chaining_hash", "")

    index: int = last_tx.get("index", 0)
    for tx in txs:
        tx_hash: str = gen_tx_hash(tx)
        if tx_hash in existing_hashes:
            continue

        tx["insertion_timestamp"] = int(time.time())
        tx["hash"] = tx_hash
        tx["chaining_hash"] = hashlib.sha256(
            (last_chaining_hash + tx_hash).encode()
        ).hexdigest()
        tx["state"] = "sequenced"
        index += 1
        tx["index"] = index
        bulk_operations.append(pymongo.InsertOne(tx))

        existing_hashes.add(tx_hash)
        last_chaining_hash = tx["chaining_hash"]

    if bulk_operations:
        txs_col.bulk_write(bulk_operations)


def upsert_sync_point(state: Dict[str, Any], sig: Any) -> None:
    nodes_states_col.update_one(
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


def is_dk_set() -> bool:
    return (
        distributed_keys.find_one(
            {"_id": "zellular", "public_shares": {"$exists": True}}
        )
        is not None
    )


def insert_dk(data: Dict[str, Any]) -> None:
    distributed_keys.update_one(
        {"_id": "zellular"},
        {
            "$set": {
                "public_shares": json.dumps(data["public_shares"]),
                "party": data["party"],
            }
        },
        upsert=True,
    )


def reinitialize_txs() -> None:
    txs_col.update_many(
        {"state": "sequenced"},
        {"$set": {"state": "initialized", "insertion_timestamp": int(time.time())}},
    )


def update_to_sequencer(last_finalized_tx: Dict[str, Any]) -> None:
    txs_col.update_many(
        {"state": "sequenced", "index": {"$lte": last_finalized_tx["index"]}},
        {"$set": {"state": "finalized"}},
    )

    index: int = last_finalized_tx["index"]
    last_chaining_hash: str = last_finalized_tx["chaining_hash"]
    cursor: Cursor = txs_col.find({"state": {"$ne": "finalized"}}).sort(
        [("index", 1), ("index", -1)]
    )
    for tx in cursor:
        index += 1
        chaining_hash: str = hashlib.sha256(
            (last_chaining_hash + tx["hash"]).encode()
        ).hexdigest()

        txs_col.update_one(
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
