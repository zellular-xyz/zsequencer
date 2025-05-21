import json

from sequencer_sabotage_simulation.schema import (
    NetworkData,
    NodeSabotageSimulationState,
    NodeSimulationStateItem,
)


def get_node_sabotage_config(
    config_file_path: str, address: str
) -> NodeSabotageSimulationState:
    return _parse_simulation_state(config_file_path)[address]


def _validate_item(item: dict) -> NodeSimulationStateItem:
    if not isinstance(item, dict):
        raise ValueError("Item must be a dictionary")
    if "time_duration" not in item or not isinstance(
        item["time_duration"], (int, float)
    ):
        raise ValueError("time_duration must be a number")
    if "up" not in item or not isinstance(item["up"], bool):
        raise ValueError("up must be a boolean")
    return item  # Type checker knows this matches NodeSimulationStateItem


def _parse_simulation_state(file_path: str) -> NetworkData:
    with open(file_path, "r") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        raise ValueError("JSON content must be a dictionary")

    # Validate the structure
    result: NetworkData = {}
    for key, value in data.items():
        if not isinstance(key, str):
            raise ValueError("All keys must be strings")
        if not isinstance(value, list):
            raise ValueError(f"Value for key '{key}' must be a list")
        # Validate each item in the list
        result[key] = [_validate_item(item) for item in value]

    return result
