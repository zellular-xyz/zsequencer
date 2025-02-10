from pydantic_settings import BaseSettings


class ProxyConfig(BaseSettings):
    PROXY_HOST: str
    PROXY_PORT: int
    NODE_HOST: str
    NODE_PORT: int
    FLUSH_THRESHOLD_VOLUME: int = 2000
    FLUSH_THRESHOLD_TIMEOUT: float = 0.1
    WORKERS_COUNT: int = 10

    class Config:
        env_prefix = "ZSEQUENCER_"
        env_file = ".env"  # Optional: Load from a .env file if available
        fields = {
            "PROXY_HOST": {"env": "ZSEQUENCER_PROXY_HOST"},
            "PROXY_PORT": {"env": "ZSEQUENCER_PROXY_PORT"},
            "NODE_HOST": {"env": "ZSEQUENCER_NODE_HOST"},
            "NODE_PORT": {"env": "ZSEQUENCER_NODE_PORT"},
            "FLUSH_THRESHOLD_VOLUME": {"env": "ZSEQUENCER_PROXY_FLUSH_THRESHOLD_VOLUME"},
            "FLUSH_THRESHOLD_TIMEOUT": {"env": "ZSEQUENCER_PROXY_FLUSH_THRESHOLD_TIMEOUT"},
            "WORKERS_COUNT": {"env": "ZSEQUENCER_PROXY_WORKERS_COUNT"},
        }
