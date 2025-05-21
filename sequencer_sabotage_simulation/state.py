import subprocess
import threading
import time

from config import zconfig
from sequencer_sabotage_simulation.utils import get_node_sabotage_config
from settings import OutOfReachSimulation


class SequencerSabotageSimulationState:
    _instance = None

    def __init__(self, conf: OutOfReachSimulation, address: str):
        self._conf = conf
        self._address = address
        self._sabotage_time_series_conf = get_node_sabotage_config(
            config_file_path=conf.timeseries_nodes_state_file, address=self._address
        )
        self._out_of_reach = (
            False
            if len(self._sabotage_time_series_conf) == 0
            else (not self._sabotage_time_series_conf[0]["up"])
        )
        self._stop_event = threading.Event()
        self._monitor_thread = None

    @staticmethod
    def get_instance(conf: OutOfReachSimulation, address: str):
        if not SequencerSabotageSimulationState._instance:
            SequencerSabotageSimulationState._instance = (
                SequencerSabotageSimulationState(conf, address)
            )
        SequencerSabotageSimulationState._instance.start_simulating()
        return SequencerSabotageSimulationState._instance

    def _simulate_out_of_reach(self):
        """Daemon thread function to periodically check the condition."""
        current_state_index = 0
        while not self._stop_event.is_set() and self._conf.out_of_reach_simulation:
            time.sleep(
                self._sabotage_time_series_conf[current_state_index]["time_duration"]
            )

            if self._out_of_reach:
                self._disable_network()
            else:
                self._enable_network()

            self._out_of_reach = not self._out_of_reach
            current_state_index += 1
            if current_state_index == len(self._sabotage_time_series_conf):
                break

    def _disable_network(self):
        """Disable network connectivity."""
        if not self._out_of_reach:
            subprocess.run(["iptables", "-P", "INPUT", "DROP"])
            subprocess.run(["iptables", "-P", "OUTPUT", "DROP"])
            subprocess.run(["iptables", "-P", "FORWARD", "DROP"])
            self._out_of_reach = True

    def _enable_network(self):
        """Enable network connectivity."""
        if self._out_of_reach:
            subprocess.run(["iptables", "-P", "INPUT", "ACCEPT"])
            subprocess.run(["iptables", "-P", "OUTPUT", "ACCEPT"])
            subprocess.run(["iptables", "-P", "FORWARD", "ACCEPT"])
            self._out_of_reach = False

    def start_simulating(self):
        """Start the daemon threads to simulate and monitor the condition."""
        # Create and start the simulation thread
        self._monitor_thread = threading.Thread(
            target=self._simulate_out_of_reach, daemon=True
        )
        self._monitor_thread.start()

    @property
    def out_of_reach(self) -> bool:
        """Public getter for the _out_of_reach flag."""
        return self._out_of_reach


sequencer_sabotage_simulation_state = SequencerSabotageSimulationState.get_instance(
    conf=OutOfReachSimulation(), address=zconfig.ADDRESS
)
