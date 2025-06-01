import os
import subprocess
import threading
import time

from common.logger import zlogger
from config import zconfig
from sabotage.schema import SabotageConf


def is_running_in_docker() -> bool:
    """Check if the code is running inside a Docker container."""
    # Check for Docker environment file
    if os.path.exists("/.dockerenv"):
        return True

    # Check cgroup info for docker indication (for older Docker versions)
    try:
        with open("/proc/1/cgroup", "rt") as f:
            return any("docker" in line or "kubepods" in line for line in f)
    except FileNotFoundError:
        return False


class SabotageSimulator:
    def __init__(self):
        self._sabotage_conf = SabotageConf.get_config(zconfig.SABOTAGE_CONFIG_FILE)
        self._out_of_reach_time_series = self._sabotage_conf.out_of_reach_time_series
        self._out_of_reach = False
        self._monitor_thread = None

    def _simulate_out_of_reach(self):
        """Daemon thread function to periodically check the condition."""
        for state in self._out_of_reach_time_series:
            self._out_of_reach = not state.up
            if self._out_of_reach:
                self._disable_network()
            else:
                self._enable_network()

            time.sleep(state.time_duration)

    def _disable_network(self):
        """Disable network connectivity."""
        zlogger.info("Disabling network")
        subprocess.run(["iptables", "-A", "OUTPUT", "-j", "DROP"], check=False)
        subprocess.run(["iptables", "-A", "INPUT", "-j", "DROP"], check=False)
        zlogger.info("Network disabled")

    def _enable_network(self):
        """Enable network connectivity."""
        zlogger.info("Enabling network")
        subprocess.run(["iptables", "-D", "OUTPUT", "-j", "DROP"], check=False)
        subprocess.run(["iptables", "-D", "INPUT", "-j", "DROP"], check=False)
        zlogger.info("Network enabled")

    def start_simulating(self):
        """Start the daemon threads to simulate and monitor the condition."""
        if not is_running_in_docker():
            zlogger.info("Not running in docker - not simulating network outages")
            return

        # Create and start the simulation thread
        self._monitor_thread = threading.Thread(
            target=self._simulate_out_of_reach, daemon=True
        )
        self._monitor_thread.start()

    @property
    def out_of_reach(self) -> bool:
        """Public getter for the _out_of_reach flag."""
        return self._out_of_reach
