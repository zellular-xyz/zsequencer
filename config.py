"""
Configuration functions for the ZSequencer.
"""

import cProfile
import functools
import json
import os
import pstats
from typing import Any

from dotenv import load_dotenv
from eigensdk.crypto.bls import attestation
from web3 import Account


class Config:
    _instance = None

    def __new__(cls) -> "Config":
        if cls._instance is None:
            cls._instance = super(Config, cls).__new__(cls)
            cls._instance.load_environment_variables()
        return cls._instance

    @staticmethod
    def load_json_file(file_path: str) -> dict[str, Any]:
        """Load JSON data from a file."""
        try:
            with open(file=file_path, mode="r", encoding="utf-8") as json_file:
                return json.load(json_file)
        except FileNotFoundError:
            print(f"File not found: {file_path}")
            return {}
        except json.JSONDecodeError:
            print(f"Error decoding JSON from file: {file_path}")
            return {}

    @staticmethod
    def validate_env_variables() -> None:
        """Validate that all required environment variables are set."""
        required_vars: list[str] = [
            "ZSEQUENCER_BLS_KEY_FILE",
            "ZSEQUENCER_BLS_KEY_PASSWORD",
            "ZSEQUENCER_ECDSA_KEY_FILE",
            "ZSEQUENCER_ECDSA_KEY_PASSWORD",
            "ZSEQUENCER_NODES_FILE",
            "ZSEQUENCER_APPS_FILE",
            "ZSEQUENCER_SNAPSHOT_PATH",
            "ZSEQUENCER_PORT",
            "ZSEQUENCER_SNAPSHOT_CHUNK",
            "ZSEQUENCER_REMOVE_CHUNK_BORDER",
            "ZSEQUENCER_THRESHOLD_PERCENT",
            "ZSEQUENCER_SEND_TXS_INTERVAL",
            "ZSEQUENCER_SYNC_INTERVAL",
            "ZSEQUENCER_FINALIZATION_TIME_BORDER",
            "ZSEQUENCER_SIGNATURES_AGGREGATION_TIMEOUT"
        ]

        missing_vars: list[str] = [var for var in required_vars if not os.getenv(var)]

        if missing_vars:
            raise EnvironmentError(
                f"Missing environment variables: {', '.join(missing_vars)}"
            )

    def get_aggregated_public_key(self) -> attestation.G2Point:
        aggregated_public_key: attestation.G2Point = attestation.new_zero_g2_point()
        for node in self.NODES.values():
            aggregated_public_key = aggregated_public_key + node["public_key_g2"]
        return aggregated_public_key

    def load_environment_variables(self):
        """Load environment variables from a .env file and validate them."""
        if os.path.exists(".env"):
            load_dotenv(dotenv_path=".env", override=False)
        self.validate_env_variables()

        self.NODES_FILE: str = os.getenv("ZSEQUENCER_NODES_FILE", "nodes.json")
        self.APPS_FILE: str = os.getenv("ZSEQUENCER_APPS_FILE", "apps.json")
        self.SNAPSHOT_PATH: str = os.getenv("ZSEQUENCER_SNAPSHOT_PATH", "./data/")

        bls_key_store_path: str = os.getenv("ZSEQUENCER_BLS_KEY_FILE", "")
        ecdsa_key_store_path: str = os.getenv("ZSEQUENCER_ECDSA_KEY_FILE", "")

        bls_key_password: str = os.getenv("ZSEQUENCER_BLS_KEY_PASSWORD", "")
        bls_key_pair: attestation.KeyPair = attestation.KeyPair.read_from_file(
            bls_key_store_path, bls_key_password)
        bls_public_key: str = bls_key_pair.pub_g2.getStr(10).decode('utf-8')
        bls_private_key: str = bls_key_pair.priv_key.getStr(10).decode('utf-8')

        ecdsa_key_password: str = os.getenv("ZSEQUENCER_ECDSA_KEY_PASSWORD", "")
        with open(ecdsa_key_store_path, 'r') as f:
            encrypted_json: str = json.loads(f.read())
        ecdsa_private_key: str = Account.decrypt(encrypted_json, ecdsa_key_password)

        self.NODES: dict[str, dict[str, Any]] = self.load_json_file(self.NODES_FILE)
        self.NODE: dict[str, Any] = {}
        for node in self.NODES.values():
            public_key_g2: str = node["public_key_g2"]
            if public_key_g2 == bls_public_key:
                self.NODE = node
            node["public_key_g2"] = attestation.new_zero_g2_point()
            node["public_key_g2"].setStr(public_key_g2.encode("utf-8"))
        if not self.NODE:
            raise EnvironmentError(
                f"A node with public key {public_key} not found in nodes.json"
            )

        self.NODE["ecdsa_private_key"] = ecdsa_private_key
        self.NODE["bls_key_pair"] = bls_key_pair

        os.makedirs(self.SNAPSHOT_PATH, exist_ok=True)

        self.PORT: int = int(os.getenv("ZSEQUENCER_PORT", "6000"))
        self.SNAPSHOT_CHUNK: int = int(os.getenv("ZSEQUENCER_SNAPSHOT_CHUNK", "1000"))
        self.REMOVE_CHUNK_BORDER: int = int(
            os.getenv("ZSEQUENCER_REMOVE_CHUNK_BORDER", "2")
        )

        self.SEND_TXS_INTERVAL: float = float(
            os.getenv("ZSEQUENCER_SEND_TXS_INTERVAL", "5")
        )
        self.SYNC_INTERVAL: float = float(os.getenv("ZSEQUENCER_SYNC_INTERVAL", "30"))
        self.FINALIZATION_TIME_BORDER: int = int(
            os.getenv("ZSEQUENCER_FINALIZATION_TIME_BORDER", "120")
        )
        self.AGGREGATION_TIMEOUT: int = int(
            os.getenv("ZSEQUENCER_SIGNATURES_AGGREGATION_TIMEOUT", "5")
        )
        self.THRESHOLD_PERCENT: int = float(
            os.getenv("ZSEQUENCER_THRESHOLD_PERCENT", str(100))
        )

        self.AGGREGATED_PUBLIC_KEY: attestation.G2Point = (
            self.get_aggregated_public_key()
        )
        self.TOTAL_STAKE = sum([node['stake'] for node in self.NODES.values()])

        self.SEQUENCER: dict[str, Any] = self.NODES["1"]

        self.APPS: dict[str, dict[str, Any]] = self.load_json_file(self.APPS_FILE)

        self.HEADERS: dict[str, Any] = {"Content-Type": "application/json"}

    def update_sequencer(self, sequencer_id: str | None) -> None:
        """Update the sequencer configuration."""
        if sequencer_id:
            self.SEQUENCER = self.NODES[sequencer_id]

    # TODO: remove
    @staticmethod
    def profile_function(output_file: str) -> Any:
        """Decorator to profile the execution of a function."""

        def decorator(func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                profiler = cProfile.Profile()
                profiler.enable()
                try:
                    result = func(*args, **kwargs)
                finally:
                    profiler.disable()
                    with open(
                        file=f"{zconfig.NODE['port']}_{output_file}",
                        mode="a",
                        encoding="utf-8",
                    ) as file:
                        ps = pstats.Stats(profiler, stream=file)
                        ps.strip_dirs().sort_stats("cumulative").print_stats()
                return result

            return wrapper

        return decorator


zconfig: Config = Config()
