import threading
import time

from config import zconfig
from sequencer_sabotage_simulation.utils import get_node_sabotage_config
from settings import SequencerSabotageSimulation


class SequencerSabotageSimulationState:
    _instance = None

    def __init__(self, conf: SequencerSabotageSimulation, address: str):
        self._conf = conf
        self._address = address
        self._sabotage_time_series_conf = get_node_sabotage_config(config_file_path=conf.timeseries_nodes_state_file,
                                                                   address=self._address)
        self._out_of_reach = False if len(self._sabotage_time_series_conf) == 0 else (not self._sabotage_time_series_conf[0]['up'])
        self._stop_event = threading.Event()  # To allow stopping the thread gracefully

    @staticmethod
    def get_instance(conf: SequencerSabotageSimulation, address: str):
        if not SequencerSabotageSimulationState._instance:
            SequencerSabotageSimulationState._instance = SequencerSabotageSimulationState(conf,
                                                                                          address)
        SequencerSabotageSimulationState._instance.start_simulating()
        return SequencerSabotageSimulationState._instance

    def _simulate_out_of_reach(self):
        """Daemon thread function to periodically check the condition."""
        current_state_index = 0
        while not self._stop_event.is_set():
            if zconfig.is_sequencer:
                # Todo: should also check this condition
                # and self._sabotage_time_series_conf.out_of_reach_simulation
                time.sleep(self._sabotage_time_series_conf[current_state_index]['time_duration'])
                self._out_of_reach = not self._out_of_reach
                current_state_index += 1
                if current_state_index == len(self._sabotage_time_series_conf):
                    break

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


sequencer_sabotage_simulation_state = SequencerSabotageSimulationState.get_instance(conf=SequencerSabotageSimulation(),
                                                                                    address=zconfig.ADDRESS)
