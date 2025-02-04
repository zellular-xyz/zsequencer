from batch_aggregator_proxy import ProxyConfig, ProxyServer


def main():
    ProxyServer(ProxyConfig.from_env()).run()


if __name__ == "__main__":
    main()
