from pydantic import Field
from pydantic_settings import BaseSettings


class ProxyConfig(BaseSettings):
    flush_threshold_volume: int = Field(default=2000)
    flush_threshold_timeout: float = Field(default=0.1)

    class Config:
        env_prefix = "ZSEQUENCER_PROXY_"


class NodeConfig(BaseSettings):
    host: str = Field(default="localhost")
    port: int = Field(default=6000)

    class Config:
        env_prefix = "ZSEQUENCER_"
