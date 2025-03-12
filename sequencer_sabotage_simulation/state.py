import threading
import time

from config import zconfig
from settings import SequencerSabotageSimulation


class SequencerSabotageSimulationState:
    """Manages the state of a sequencer sabotage simulation, including out-of-reach conditions."""

    def __init__(self, conf: SequencerSabotageSimulation):
        """Initialize the simulation state with configuration.

        Args:
            conf: Configuration object containing simulation parameters.
        """
        self._conf = conf  # Store the simulation configuration
        self._out_of_reach = False  # Flag indicating if sequencer is out of reach
        self._stop_event = threading.Event()  # Event to signal thread termination

    def _simulate_out_of_reach(self):
        """Daemon thread function to periodically toggle the out-of-reach condition.

        Runs in a loop, simulating periods of being in and out of reach based on config timings,
        until the stop event is triggered.
        """
        while not self._stop_event.is_set():
            if zconfig.is_sequencer and self._conf.out_of_reach_simulation:
                # Simulate in-reach period
                self._out_of_reach = False
                time.sleep(self._conf.in_reach_seconds)  # Wait for in-reach duration
                # Simulate out-of-reach period
                self._out_of_reach = True
                time.sleep(self._conf.out_of_reach_seconds)  # Wait for out-of-reach duration
            # Short sleep to prevent tight loop when simulation is off or not a sequencer
            time.sleep(0.01)  # Adjust this interval for responsiveness vs. CPU usage

    def start_simulating(self):
        """Start the daemon thread to monitor and simulate the out-of-reach condition.

        The thread runs as a daemon, meaning it will terminate when the main program exits.
        """
        # Create and start the daemon thread
        thread = threading.Thread(target=self._simulate_out_of_reach, daemon=True)
        thread.start()

    def stop_simulating(self):
        """Stop the daemon thread gracefully by setting the stop event."""
        self._stop_event.set()

    @property
    def out_of_reach(self) -> bool:
        """Public getter for the out-of-reach status.

        Returns:
            bool: True if the sequencer is currently simulated as out of reach, False otherwise.
        """
        return self._out_of_reach


# Instantiate the simulation state with configuration from SequencerSabotageSimulation
sequencer_sabotage_simulation_state = SequencerSabotageSimulationState(
    conf=SequencerSabotageSimulation()
)
