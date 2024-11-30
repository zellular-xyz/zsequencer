import json
import time
import random
from typing import Any

import requests
from eigensdk.crypto.bls import attestation
from eigensdk.chainio.clients.builder import BuildAllConfig, build_all

import xxhash

hash = xxhash.xxh128_hexdigest


def get_operators():
    subgraph_url = (
        "https://api.studio.thegraph.com/query/85556/bls_apk_registry/version/latest"
    )
    query = """
        query MyQuery {
          operators {
            id
            operatorId
            pubkeyG1_X
            pubkeyG1_Y
            pubkeyG2_X
            pubkeyG2_Y
            socket
            stake
          }
        }
    """
    resp = requests.post(subgraph_url, json={"query": query})
    operators = resp.json()["data"]["operators"]

    for operator in operators:
        operator["stake"] = min(1, float(operator["stake"]) / (10 ** 18))
        public_key_g2 = (
                "1 "
                + operator["pubkeyG2_X"][1]
                + " "
                + operator["pubkeyG2_X"][0]
                + " "
                + operator["pubkeyG2_Y"][1]
                + " "
                + operator["pubkeyG2_Y"][0]
        )
        operator["public_key_g2"] = attestation.new_zero_g2_point()
        operator["public_key_g2"].setStr(public_key_g2.encode("utf-8"))

    operators = {operator["id"]: operator for operator in operators}
    return operators


class Zellular:
    def __init__(self, app_name, base_url, operators=None, threshold_percent=67):
        self.app_name = app_name
        self.base_url = base_url
        self.threshold_percent = threshold_percent
        self.operators = operators if operators else get_operators()
        self.aggregated_public_key = attestation.new_zero_g2_point()

        for operator in self.operators.values():
            self.aggregated_public_key += operator["public_key_g2"]

    def verify_signature(self, message, signature_hex, nonsigners):
        total_stake = sum([operator["stake"] for operator in self.operators.values()])
        nonsigners = [self.operators[_id] for _id in nonsigners]
        nonsigners_stake = sum([operator["stake"] for operator in nonsigners])
        if 100 * nonsigners_stake / total_stake > 100 - self.threshold_percent:
            return False

        public_key = self.aggregated_public_key
        for operator in nonsigners:
            public_key -= operator["public_key_g2"]

        signature = attestation.new_zero_signature()
        signature.setStr(signature_hex.encode("utf-8"))

        message = hash(message)
        return signature.verify(public_key, message.encode("utf-8"))

    def verify_finalized(self, data, batch_hash, chaining_hash):
        message = json.dumps(
            {
                "app_name": self.app_name,
                "state": "locked",
                "index": data["index"],
                "hash": batch_hash,
                "chaining_hash": chaining_hash,
            },
            sort_keys=True,
        )

        signature = data["finalization_signature"]
        nonsigners = data.get("nonsigners", [])
        result = self.verify_signature(
            message,
            signature,
            nonsigners,
        )
        print(f"app: {self.app_name}, index: {data['index']}, verification result: {result}")
        return result

    def get_finalized(self, after, chaining_hash):
        res = []
        index = after if chaining_hash != None else after - 1
        while True:
            resp = requests.get(
                f"{self.base_url}/node/{self.app_name}/batches/finalized?after={index}"
            )
            data = resp.json()["data"]
            if not data:
                continue
            batches = data["batches"]
            finalized = data["finalized"]
            if chaining_hash == None:
                chaining_hash = data["first_chaining_hash"]
                batches = batches[1:]
                index += 1

            for batch in batches:
                index += 1
                chaining_hash = hash(chaining_hash + hash(batch))
                res.append(batch)
                if finalized and index == finalized["index"]:
                    assert (
                        self.verify_finalized(finalized, hash(batch), chaining_hash)
                    ), "invalid signature"
                    return chaining_hash, res

    def iterate_batches(self, after=0):
        assert after >= 0, "after should be equal or bigger than 0"
        chaining_hash = "" if after == 0 else None
        while True:
            chaining_hash, batches = self.get_finalized(after, chaining_hash)
            for batch in batches:
                after += 1
                yield batch, after

    def get_last_finalized(self):
        url = f"{self.base_url}/node/{self.app_name}/batches/finalized/last"
        resp = requests.get(url)
        data = resp.json()["data"]
        verified = self.verify_finalized(data, data["hash"], data["chaining_hash"])
        assert verified, "invalid signature"
        return data

    def send(self, batch, blocking=False):
        if blocking:
            index = self.get_last_finalized()["index"]

        url = f"{self.base_url}/node/{self.app_name}/batches"
        resp = requests.put(url, json=batch)
        assert resp.status_code == 200

        if not blocking:
            return

        # Todo: why?
        for received_batch, index in self.iterate_batches(after=index):
            received_batch = json.loads(received_batch)
            if batch == received_batch:
                return index
