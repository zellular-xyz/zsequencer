from typing import List

from pydantic import BaseModel, ConfigDict


class OutOfReachItem(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    time_duration: float
    up: bool


class SabotageConf(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    out_of_reach_time_series: List[OutOfReachItem]
