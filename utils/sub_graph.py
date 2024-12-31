import requests


def get_eigen_network_info(sub_graph_socket: str, block_number: int):
    graphql_query = {
        "query": f"""
{{
    operators(block: {{ number: {block_number} }}) {{
        id
        socket
        stake
        pubkeyG2_X
        pubkeyG2_Y
    }}
}}
"""
    }

    response = requests.post(sub_graph_socket,
                             headers={"content-type": "application/json"},
                             json=graphql_query)
    result = response.json()
    return {
        item.get("id"): {
            "id": item.get("id"),
            "address": item.get("id"),
            "socket": item.get("socket"),
            "stake": int(item.get("socket")),
            "public_key_g2": '1 ' + item['pubkeyG2_X'][1] + ' ' + item['pubkeyG2_X'][0] + ' ' \
                             + item['pubkeyG2_Y'][1] + ' ' + item['pubkeyG2_Y'][0]
        }
        for item in result.get("data").get("operators", [])
    }


def fetch_eigen_layer_last_block_number(sub_graph_socket: str) -> int:
    response = requests.post(sub_graph_socket,
                             headers={"content-type": "application/json"},
                             json={"query": "{ _meta { block { number } } }"})

    if response.status_code == 200:
        block_number = int(response.json()["data"]["_meta"]["block"]["number"])
        return block_number
