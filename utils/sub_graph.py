import requests

default_nodes_list = {
    "0x747b80a1c0b0e6031b389e3b7eaf9b5f759f34ed",
    "0x3eaa1c283dbf13357257e652649784a4cc08078c",
    "0x906585f83fa7d29b96642aa8f7b4267ab42b7b6c",
    "0x93d89ade53b8fcca53736be1a0d11d342d71118b",
}


def get_stake(operator: dict) -> int:
    stake: float = int(operator.get("stake", 0)) / (10**18)
    return stake if operator.get("id") in default_nodes_list else min(stake, 1)


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
""",
    }

    response = requests.post(
        sub_graph_socket,
        headers={"content-type": "application/json"},
        json=graphql_query,
    )
    result = response.json()

    return {
        item.get("id"): {
            "id": item.get("id"),
            "address": item.get("id"),
            "socket": item.get("socket"),
            "stake": get_stake(item),
            "public_key_g2": "1 "
            + item["pubkeyG2_X"][1]
            + " "
            + item["pubkeyG2_X"][0]
            + " "
            + item["pubkeyG2_Y"][1]
            + " "
            + item["pubkeyG2_Y"][0],
        }
        for item in result.get("data").get("operators", [])
    }


def fetch_eigen_layer_last_block_number(sub_graph_socket: str) -> int:
    response = requests.post(
        sub_graph_socket,
        headers={"content-type": "application/json"},
        json={"query": "{ _meta { block { number } } }"},
    )

    if response.status_code == 200:
        block_number = int(response.json()["data"]["_meta"]["block"]["number"])
        # add a delay to ensure no reorg happens
        return block_number - 5


if __name__ == "__main__":
    url = "https://api.studio.thegraph.com/query/95922/avs-subgraph/version/latest"
    block_number = fetch_eigen_layer_last_block_number(url)
    operators = get_eigen_network_info(url, block_number)
    total = 0
    for _, op in operators.items():
        print(op["socket"], op["stake"])
        total += op["stake"]
    print(total)
