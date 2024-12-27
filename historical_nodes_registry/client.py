import requests
from urllib.parse import urljoin
from typing import Optional
from historical_nodes_registry.schema import NodeInfo, SnapShotType


class NodesRegistryClient:
    def __init__(self, socket: str):
        self.base_url = f'http://{socket}' if not socket.startswith(('http://', 'https://')) else socket

    def add_snapshot(self, nodes_info_snapshot: SnapShotType):
        nodes_info_snapshot_dict = {
            address: node_info.dict()
            for address, node_info in nodes_info_snapshot.items()
        }
        try:
            response = requests.post(urljoin(self.base_url, '/snapshot/'), json=nodes_info_snapshot_dict)
            response.raise_for_status()
            return response.json()

        except requests.HTTPError as http_err:
            print(f"HTTP error occurred: {http_err}")  # HTTP error details
        except Exception as err:
            print(f"An error occurred: {err}")  # General error details

    def add_node_info(self, node_info: NodeInfo):
        try:
            response = requests.post(urljoin(self.base_url, '/nodeInfo/'), json=node_info.dict())
            response.raise_for_status()
            return response.json()

        except requests.HTTPError as http_err:
            print(f"HTTP error occurred: {http_err}")  # HTTP error details
        except Exception as err:
            print(f"An error occurred: {err}")  # General error details

    def get_network_snapshot(self, timestamp: Optional[int]) -> SnapShotType:
        try:
            if timestamp is None:
                response = requests.get(urljoin(self.base_url, '/snapshot/'))
            else:
                response = requests.get(urljoin(self.base_url, '/snapshot/'), params={"timestamp": timestamp})
            response.raise_for_status()
            snapshot: SnapShotType = {address: NodeInfo(**node_info_dict)
                                      for address, node_info_dict in response.json().get('snapshot').items()}
            return snapshot
        except requests.HTTPError as http_err:
            print(f"HTTP error occurred: {http_err}")  # HTTP error details
        except Exception as err:
            print(f"An error occurred: {err}")  # General error details
