from typing import TypeAlias, TypedDict


class NodeSimulationStateItem(TypedDict):
    time_duration: float
    up: bool


NodeSabotageSimulationState: TypeAlias = list[NodeSimulationStateItem]
NetworkData: TypeAlias = dict[str, NodeSabotageSimulationState]
