import json

from config import zconfig
from sabotage.schema import (
    OutOfReachItem,
    SabotageConf,
)


def get_sabotage_config() -> SabotageConf:
    if zconfig.SABOTAGE_SIMULATION:
        with open(zconfig.SABOTAGE_CONFIG_FILE, "r") as file:
            data = json.load(file)

        return _parse_simulation_config(data)
    else:
        return {"out_of_reach_time_series": []}


def _parse_item(item: dict) -> OutOfReachItem:
    if not isinstance(item, dict):
        raise ValueError("Item must be a dictionary")
    if "time_duration" not in item or not isinstance(
        item["time_duration"], (int, float)
    ):
        raise ValueError("time_duration must be a number")
    if "up" not in item or not isinstance(item["up"], bool):
        raise ValueError("up must be a boolean")
    return item


def _parse_simulation_config(data: dict) -> SabotageConf:
    if not isinstance(data, dict):
        raise ValueError("JSON content must be a dict")

    out_of_reach_time_series = []
    if "out_of_reach_time_series" in data:
        out_of_reach_time_series = [
            _parse_item(item) for item in data["out_of_reach_time_series"]
        ]

    return {"out_of_reach_time_series": out_of_reach_time_series}
