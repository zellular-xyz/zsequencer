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
            "ZSEQUENCER_PORT",
            "ZSEQUENCER_FLASK_SECRET_KEY",
            "ZSEQUENCER_PUBLIC_KEY",
            "ZSEQUENCER_PRIVATE_KEY",
            "ZSEQUENCER_NODES_FILE",
            "ZSEQUENCER_SNAPSHOT_CHUNK",
            "ZSEQUENCER_REMOVE_CHUNK_BORDER",
            "ZSEQUENCER_SNAPSHOT_PATH",
            "ZSEQUENCER_THRESHOLD_NUMBER",
            "ZSEQUENCER_SEND_TXS_INTERVAL",
            "ZSEQUENCER_SYNC_INTERVAL",
            "ZSEQUENCER_FINALIZATION_TIME_BORDER",
        ]

        missing_vars: list[str] = [var for var in required_vars if not os.getenv(var)]

        if missing_vars:
            raise EnvironmentError(
                f"Missing environment variables: {', '.join(missing_vars)}"
            )

    def get_aggregated_public_key(self) -> attestation.G2Point:
        aggregated_public_key: attestation.G2Point = attestation.new_zero_g2_point()
        for node in self.NODES.values():
            public_key: attestation.G2Point = attestation.new_zero_g2_point()
            public_key.setStr(node["public_key"].encode("utf-8"))
            aggregated_public_key = aggregated_public_key + public_key
        return aggregated_public_key

    def load_environment_variables(self):
        """Load environment variables from a .env file and validate them."""
        env: str = os.getenv("ZSEQUENCER_ENV_PATH", "production")
        env_file: str = f"{env}.env"
        load_dotenv(dotenv_path=env_file, override=True)
        self.validate_env_variables()

        self.PORT: int = int(os.getenv("ZSEQUENCER_PORT", "6000"))
        self.SNAPSHOT_CHUNK: int = int(os.getenv("ZSEQUENCER_SNAPSHOT_CHUNK", "1000"))
        self.REMOVE_CHUNK_BORDER: int = int(
            os.getenv("ZSEQUENCER_REMOVE_CHUNK_BORDER", "2")
        )
        self.SNAPSHOT_PATH: str = os.getenv("ZSEQUENCER_SNAPSHOT_PATH", "./data/")
        os.makedirs(self.SNAPSHOT_PATH, exist_ok=True)
        self.FLASK_SECRET_KEY: str = os.getenv("ZSEQUENCER_FLASK_SECRET_KEY", "")
        self.PUBLIC_KEY: str = os.getenv("ZSEQUENCER_PUBLIC_KEY", "")
        self.SEND_TXS_INTERVAL: float = float(
            os.getenv("ZSEQUENCER_SEND_TXS_INTERVAL", "5")
        )
        self.SYNC_INTERVAL: float = float(os.getenv("ZSEQUENCER_SYNC_INTERVAL", "30"))
        self.FINALIZATION_TIME_BORDER: int = int(
            os.getenv("ZSEQUENCER_FINALIZATION_TIME_BORDER", "120")
        )
        self.NODES_FILE: str = os.getenv("ZSEQUENCER_NODES_FILE", "nodes.json")
        self.NODES: dict[str, dict[str, Any]] = self.load_json_file(self.NODES_FILE)
        for node in self.NODES.values():
            node["public_key_g2"] = attestation.new_zero_g2_point()
            node["public_key_g2"].setStr(node["public_key"].encode("utf-8"))

        self.THRESHOLD_NUMBER: int = int(
            os.getenv("ZSEQUENCER_THRESHOLD_NUMBER", str(len(self.NODES)))
        )
        self.NODE: dict[str, Any] = next(
            (n for n in self.NODES.values() if n["public_key"] == self.PUBLIC_KEY), {}
        )
        self.NODE["private_key"] = os.getenv("ZSEQUENCER_PRIVATE_KEY", "")
        self.NODE["key_pair"] = attestation.new_key_pair_from_string(
            self.NODE["private_key"]
        )

        self.AGGREGATED_PUBLIC_KEY: attestation.G2Point = (
            self.get_aggregated_public_key()
        )

        self.SEQUENCER: dict[str, Any] = self.NODES["1"]

        self.APPS_FILE: str = os.getenv("ZSEQUENCER_APPS_FILE", "apps.json")
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
