import uvicorn
from batch_aggregator_proxy import ProxyConfig


def main():
    config = ProxyConfig.from_env()

    uvicorn.run("batch_aggregator_proxy.proxy_server:app",
                host=config.PROXY_HOST,
                port=config.PROXY_PORT,
                workers=config.WORKERS_COUNT)


if __name__ == "__main__":
    main()
