import json
import math
import os
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv


class Config:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Config, cls).__new__(cls)
            cls._instance.load_environment_variables()
        return cls._instance

    def load_environment_variables(self):
        env = os.getenv("ZSEQUENCER_ENV_PATH", "production")
        env_file = f"{env}.env"
        load_dotenv(dotenv_path=env_file, override=True)

        self.PORT: int = int(os.getenv("ZSEQUENCER_PORT", default=6000))
        self.SNAPSHOT_CHUNK: int = int(
            os.getenv("ZSEQUENCER_SNAPSHOT_CHUNK", default=1000)
        )
        self.REMOVE_CHUNK_BORDER = int(
            os.getenv("ZSEQUENCER_REMOVE_CHUNK_BORDER", default=2)
        )
        self.SNAPSHOT_PATH: str = os.getenv(
            "ZSEQUENCER_SNAPSHOT_PATH", default="./data/"
        )
        os.makedirs(self.SNAPSHOT_PATH, exist_ok=True)
        self.SECRET_KEY: Optional[str] = os.getenv("ZSEQUENCER_SECRET_KEY")
        self.PUBLIC_KEY: int = int(os.getenv("ZSEQUENCER_PUBLIC_KEY", default=0))
        self.SEND_TXS_INTERVAL: int = int(
            os.getenv("ZSEQUENCER_SEND_TXS_INTERVAL", default=5)
        )
        self.SYNC_INTERVAL: int = int(os.getenv("ZSEQUENCER_SYNC_INTERVAL", default=30))
        self.MIN_NONCES: int = int(os.getenv("ZSEQUENCER_MIN_NONCES", default=10))
        self.FINALIZATION_TIME_BORDER: int = int(
            os.getenv("ZSEQUENCER_FINALIZATION_TIME_BORDER", default=120)
        )
        self.NODES_FILE: str = os.getenv("ZSEQUENCER_NODES_FILE", default="nodes.js")
        self.NODES: Dict[str, Dict[str, Any]] = self.load_nodes(self.NODES_FILE)
        self.THRESHOLD_NUMBER: int = int(
            os.getenv(
                "ZSEQUENCER_THRESHOLD_NUMBER", default=int(math.ceil(len(self.NODES)))
            )
        )
        self.NODE: Dict[str, int] = next(
            (n for n in self.NODES.values() if n["public_key"] == self.PUBLIC_KEY), {}
        )
        self.NODE["private_key"] = int(os.getenv("ZSEQUENCER_PRIVATE_KEY", default=0))
        self.SEQUENCER: Dict[str, Any] = self.NODES["1"]

        self.validate_env_variables()

    def load_nodes(self, file_path: str) -> Dict[str, Dict[str, int]]:
        with open(file_path, "r") as json_file:
            nodes_data: Dict[str, Dict[str, int]] = json.load(json_file)
        return nodes_data

    def update_sequencer(self, sequencer_id: Optional[str]) -> None:
        if sequencer_id:
            self.SEQUENCER = self.NODES[sequencer_id]

    def validate_env_variables(self):
        required_vars: List[str] = [
            "ZSEQUENCER_PORT",
            "ZSEQUENCER_SECRET_KEY",
            "ZSEQUENCER_PUBLIC_KEY",
            "ZSEQUENCER_PRIVATE_KEY",
            "ZSEQUENCER_NODES_FILE",
            "ZSEQUENCER_SNAPSHOT_CHUNK",
            "ZSEQUENCER_REMOVE_CHUNK_BORDER",
            "ZSEQUENCER_SNAPSHOT_PATH",
            "ZSEQUENCER_THRESHOLD_NUMBER",
            "ZSEQUENCER_SEND_TXS_INTERVAL",
            "ZSEQUENCER_SYNC_INTERVAL",
            "ZSEQUENCER_MIN_NONCES",
            "ZSEQUENCER_FINALIZATION_TIME_BORDER",
        ]

        missing_vars: List[str] = [var for var in required_vars if not os.getenv(var)]

        if missing_vars:
            raise EnvironmentError(
                f"Missing environment variables: {', '.join(missing_vars)}"
            )


zconfig: Config = Config()
