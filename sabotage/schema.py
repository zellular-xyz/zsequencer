from typing import TypedDict


class OutOfReachItem(TypedDict):
    time_duration: float
    up: bool


class SabotageConf(TypedDict):
    out_of_reach_time_series: list[OutOfReachItem]
