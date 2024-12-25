import bisect
import json
import threading
import time
from pathlib import Path
from typing import Dict, Optional, List, Tuple

from historical_nodes_registry.schema import NodeInfo, SnapShotType


class RegistryStateManager:
    """Manages a time series of node snapshots and the current state of nodes."""

    def __init__(self, snapshots_file_path: str,
                 commitment_interval: float,
                 logger):
        self._snapshots_file_path = snapshots_file_path
        self._snapshots: List[Tuple[float, SnapShotType]] = []
        self._last_timestamp: Optional[float] = None
        self._last_snapshot: Optional[SnapShotType] = None
        self._temporary_snapshot: SnapShotType = {}
        self._commitment_interval = commitment_interval
        self._logger = logger
        self._lock = threading.Lock()  # Protect shared resources
        self._load_snapshots()

    @staticmethod
    def _parse_snapshot(snapshot_data) -> SnapShotType:
        return {
            address: NodeInfo.parse_obj(node_info_data)
            for address, node_info_data in snapshot_data.items()
        }

    @staticmethod
    def _serialize_snapshot(snapshot: SnapShotType) -> Dict:
        return {
            address: node_info.dict()
            for address, node_info in snapshot.items()
        }

    def _load_snapshots(self):
        """Load snapshots from a JSON file."""
        file_path = Path(self._snapshots_file_path)

        # Ensure the directory and file exist
        if not file_path.exists():
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text("[]")
            self._snapshots = []
            self._last_timestamp = None
            self._last_snapshot = None
            self._logger.info("No snapshots Found")
            return

        try:
            raw_snapshots = json.loads(file_path.read_text())
            self._snapshots = sorted(
                [(float(timestamp), self._parse_snapshot(snapshot_data))
                 for timestamp, snapshot_data in raw_snapshots],
                key=lambda x: x[0])
            if len(self._snapshots) > 0:
                self._last_timestamp = self._snapshots[-1][0]
                self._last_snapshot = self._snapshots[-1][1]
            else:
                self._last_timestamp = None
                self._last_snapshot = None
            self._logger.info(f"Loaded {len(self._snapshots)} snapshots")
        except (json.JSONDecodeError, ValueError) as e:
            raise ValueError(f"Error loading snapshots from {file_path}: {e}")

    def _persist_snapshots(self):
        """Save snapshots to a JSON file."""
        timeseries_snapshots = [
            (timestamp, self._serialize_snapshot(snapshot))
            for timestamp, snapshot in self._snapshots
        ]
        with open(self._snapshots_file_path, "w") as snapshot_file:
            json.dump(timeseries_snapshots, snapshot_file)

    def get_snapshot_by_timestamp(self, query_timestamp: Optional[float]) -> Tuple[float, SnapShotType]:
        """
        Retrieve the last snapshot before or equal to the given timestamp.

        Args:
            query_timestamp (float): The timestamp to query.

        Returns:
            Any: The snapshot data.

        Raises:
            ValueError: If the query timestamp is earlier than the first snapshot.
        """
        if query_timestamp is None:
            return self._last_timestamp, self._last_snapshot

        timestamps = [ts for ts, _ in self._snapshots]

        # Exact match
        if query_timestamp in timestamps:
            idx = timestamps.index(query_timestamp)
            return self._snapshots[idx]

        # Closest match
        idx = bisect.bisect_right(timestamps, query_timestamp) - 1
        if idx < 0:
            raise ValueError("Query timestamp is earlier than the first snapshot.")
        return self._snapshots[idx]

    def update_temporary_snapshot(self, snapshot: SnapShotType):
        """Update the current node state."""
        with self._lock:
            self._temporary_snapshot = snapshot

    def update_node_info(self, node_info: NodeInfo):
        with self._lock:
            self._temporary_snapshot[node_info.id] = node_info

    def _commit_snapshot(self):
        """Commit the current state to the snapshot time series."""
        with self._lock:
            if self._temporary_snapshot != self._last_snapshot:
                now_timestamp = time.time()
                self._snapshots.append((now_timestamp, self._temporary_snapshot))
                self._last_snapshot = self._temporary_snapshot
                self._last_timestamp = now_timestamp
                self._persist_snapshots()

    def run(self):
        """Run the state manager in a loop."""
        while True:
            self._commit_snapshot()
            time.sleep(self._commitment_interval)
