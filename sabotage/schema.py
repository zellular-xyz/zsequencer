import json

from pydantic import BaseModel, ConfigDict


class OutOfReachItem(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    time_duration: float
    up: bool


class SabotageConf(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    out_of_reach_time_series: list[OutOfReachItem]

    @classmethod
    def get_config(cls, config_file: str) -> "SabotageConf":
        """Load sabotage configuration from config file."""
        with open(config_file, "r") as file:
            data = json.load(file)
        return cls.model_validate(data)
