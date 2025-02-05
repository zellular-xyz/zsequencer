import os

from pydantic import BaseModel


class ProxyConfig(BaseModel):
    PROXY_HOST: str
    PROXY_PORT: int

    NODE_HOST: str
    NODE_PORT: int
    FLUSH_THRESHOLD_VOLUME: int
    WORKERS_COUNT: int

    @classmethod
    def from_env(cls):
        return cls(PROXY_HOST=os.getenv("PROXY_HOST"),
                   PROXY_PORT=int(os.getenv("PROXY_PORT")),
                   NODE_HOST=os.getenv("ZSEQUENCER_HOST"),
                   NODE_PORT=int(os.getenv("ZSEQUENCER_PORT")),
                   FLUSH_THRESHOLD_VOLUME=int(os.getenv("PROXY_FLUSH_THRESHOLD_VOLUME", "2000")),
                   WORKERS_COUNT=int(os.getenv("PROXY_WORKERS_COUNT", "4")))
