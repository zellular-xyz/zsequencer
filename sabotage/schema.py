from pydantic import BaseModel


class OutOfReachItem(BaseModel):
    time_duration: float
    up: bool


class SabotageConf(BaseModel):
    out_of_reach_time_series: list[OutOfReachItem]
