from pydantic import Field
from pydantic_settings import BaseSettings


class ProxyConfig(BaseSettings):
    PROXY_HOST: str = Field(default="0.0.0.0")
    PROXY_PORT: int = Field(default=7000)
    HOST: str = Field(default="localhost")
    PORT: int = Field(default=6000)
    PROXY_FLUSH_THRESHOLD_VOLUME: int = Field(default=2000)
    PROXY_FLUSH_THRESHOLD_TIMEOUT: float = Field(default=0.1)
    PROXY_WORKERS_COUNT: int = Field(default=4)

    class Config:
        env_prefix = "ZSEQUENCER_"
