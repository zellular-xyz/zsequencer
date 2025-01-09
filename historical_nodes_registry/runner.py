import uvicorn

from historical_nodes_registry.server import create_server_app

registry_host = 'localhost'
registry_port = 8000


def run_registry_server(host, port):
    snapshot_server_app = create_server_app()
    config = uvicorn.Config(snapshot_server_app, host=host, port=port)
    server = uvicorn.Server(config)
    server.run()


if __name__ == "__main__":
    run_registry_server(host=registry_host, port=registry_port)
