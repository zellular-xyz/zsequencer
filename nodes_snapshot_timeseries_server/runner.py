import uvicorn

from nodes_snapshot_timeseries_server.server import create_server_app

params = {
    'persistence_filepath': '/tmp/zellular-network/nodes-snapshots.json',
    'commitment_interval': 5
}

host = 'localhost'
port = 8000


def main():
    snapshot_server_app = create_server_app(**params)
    config = uvicorn.Config(snapshot_server_app, host=host, port=port)
    server = uvicorn.Server(config)
    server.run()


if __name__ == "__main__":
    main()
