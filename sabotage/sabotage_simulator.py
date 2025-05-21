import subprocess
import threading
import time

from common.logger import zlogger
from sabotage.utils import get_sabotage_config


class SabotageSimulator:
    _instance = None

    def __init__(self):
        self._sabotage_conf = get_sabotage_config()
        self._out_of_reach_time_series = self._sabotage_conf["out_of_reach_time_series"]
        self._out_of_reach = (
            False
            if len(self._out_of_reach_time_series) == 0
            else (not self._out_of_reach_time_series[0]["up"])
        )
        self._stop_event = threading.Event()
        self._monitor_thread = None

    @staticmethod
    def get_instance():
        if not SabotageSimulator._instance:
            SabotageSimulator._instance = SabotageSimulator()

        SabotageSimulator._instance.start_simulating()
        return SabotageSimulator._instance

    def _simulate_out_of_reach(self):
        """Daemon thread function to periodically check the condition."""
        current_state_index = 0
        while not self._stop_event.is_set() and self._out_of_reach_time_series:
            if self._out_of_reach:
                self._disable_network()
            else:
                self._enable_network()

            time.sleep(
                self._out_of_reach_time_series[current_state_index]["time_duration"]
            )
            self._out_of_reach = not self._out_of_reach

            current_state_index += 1
            if current_state_index == len(self._out_of_reach_time_series):
                break

    def _disable_network(self):
        """Disable network connectivity."""
        zlogger.info("disable network")
        subprocess.run("ip link set lo down", shell=True, check=True)

    def _enable_network(self):
        """Enable network connectivity."""
        zlogger.info("enable network")
        subprocess.run("ip link set lo up", shell=True, check=True)

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


sabotage_simulator = SabotageSimulator.get_instance()
