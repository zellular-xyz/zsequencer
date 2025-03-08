class SequencerSabotageSimulationState:
    def __init__(self, out_of_reach_seconds: int):
        self._out_of_reach_seconds = out_of_reach_seconds
        self._out_of_reach = False
