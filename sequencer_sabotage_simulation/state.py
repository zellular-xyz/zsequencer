from config import zconfig
from settings import SequencerSabotageSimulation
import threading
import time


class SequencerSabotageSimulationState:
    _instance = None

    def __init__(self, conf: SequencerSabotageSimulation):
        self._conf = conf
        self._out_of_reach = False
        self._stop_event = threading.Event()  # To allow stopping the thread gracefully

    @staticmethod
    def get_instance(conf: SequencerSabotageSimulation):
        if not SequencerSabotageSimulationState._instance:
            SequencerSabotageSimulationState._instance = SequencerSabotageSimulationState(conf=conf)
        return SequencerSabotageSimulationState._instance

    def _simulate_out_of_reach(self):
        """Daemon thread function to periodically check the condition."""
        while not self._stop_event.is_set():
            if zconfig.is_sequencer:
                # Simulate a delay to represent "out of reach" duration
                self._out_of_reach = False
                time.sleep(self._conf.in_reach_seconds)
                self._out_of_reach = True
                time.sleep(self._conf.out_of_reach_seconds)
            # Sleep for a short interval before checking again
            time.sleep(0.01)  # Adjust this interval as needed

    def start_simulating(self):
        """Start the daemon thread to monitor the condition."""
        # Create and start the daemon thread
        thread = threading.Thread(target=self._simulate_out_of_reach, daemon=True)
        thread.start()

    def stop_simulating(self):
        """Stop the daemon thread gracefully."""
        self._stop_event.set()

    @property
    def out_of_reach(self) -> bool:
        """Public getter for the _out_of_reach flag."""
        return self._out_of_reach


sequencer_sabotage_simulation_state = SequencerSabotageSimulationState.get_instance(conf=SequencerSabotageSimulation())
