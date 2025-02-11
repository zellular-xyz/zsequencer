import os

from pydantic import BaseModel


class ProxyConfig(BaseModel):
    PROXY_HOST: str
    PROXY_PORT: int
    NODE_HOST: str
    NODE_PORT: int
    FLUSH_THRESHOLD_VOLUME: int
    FLUSH_THRESHOLD_TIMEOUT: float
    WORKERS_COUNT: int

    @classmethod
    def from_env(cls):
        return cls(PROXY_HOST=os.getenv("ZSEQUENCER_PROXY_HOST", "0.0.0.0"),
                   PROXY_PORT=int(os.getenv("ZSEQUENCER_PROXY_PORT", "6001")),
                   NODE_HOST=os.getenv("ZSEQUENCER_HOST", "localhost"),
                   NODE_PORT=int(os.getenv("ZSEQUENCER_PORT", "6002")),
                   FLUSH_THRESHOLD_VOLUME=int(os.getenv("ZSEQUENCER_PROXY_FLUSH_THRESHOLD_VOLUME", "2000")),
                   FLUSH_THRESHOLD_TIMEOUT=float(os.getenv("ZSEQUENCER_PROXY_FLUSH_THRESHOLD_TIMEOUT", "0.1")),
                   WORKERS_COUNT=int(os.getenv("ZSEQUENCER_PROXY_WORKERS_COUNT", "4")))
