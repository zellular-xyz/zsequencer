import time

from settings import SequencerSabotageSimulation


class SequencerSabotageSimulationState:
    """Manages the state of a sequencer sabotage simulation, including out-of-reach conditions."""

    def __init__(self, conf: SequencerSabotageSimulation):
        """Initialize the simulation state with configuration.

        Args:
            conf: Configuration object containing simulation parameters.
        """
        self._conf = conf
        self._initial_timestamp_ms = self.get_current_timestamp_ms()

    @staticmethod
    def get_current_timestamp_ms() -> int:
        """Return the current Unix timestamp in milliseconds."""
        return int(time.time() * 1000)

    @property
    def out_of_reach(self) -> bool:
        """Public getter for the out-of-reach status.

        Returns:
            bool: True if the sequencer is currently simulated as out of reach, False otherwise.
        """
        # If simulation is disabled or not a sequencer, always return False
        if not self._conf.out_of_reach_simulation:
            return False

        # Get current time and calculate elapsed time in milliseconds
        current_timestamp_ms = self.get_current_timestamp_ms()
        elapsed_ms = current_timestamp_ms - self._initial_timestamp_ms

        # Convert config durations to milliseconds
        in_reach_ms = self._conf.in_reach_seconds * 1000
        out_of_reach_ms = self._conf.out_of_reach_seconds * 1000
        cycle_length_ms = in_reach_ms + out_of_reach_ms

        # Calculate position within the current cycle using modulo
        cycle_position_ms = elapsed_ms % cycle_length_ms

        # If position is within in_reach_ms, we're in reach (return False)
        # Otherwise, we're in the out_of_reach phase (return True)
        return cycle_position_ms >= in_reach_ms


# Instantiate the simulation state with configuration from SequencerSabotageSimulation
sequencer_sabotage_simulation_state = SequencerSabotageSimulationState(
    conf=SequencerSabotageSimulation()
)
