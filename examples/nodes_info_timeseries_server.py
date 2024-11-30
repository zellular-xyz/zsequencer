import json
import bisect
import time
import threading
from fastapi import FastAPI, Depends, HTTPException
from examples.utils import deep_merge

app = FastAPI()
NODES_SNAPSHOT_FILE_PATH = 'nodes-snapshots.json'


class NodesSnapshotTimeSeries:
    def __init__(self, snapshots_file_path):
        self.snapshots_file_path = snapshots_file_path
        self.snapshots = []
        self.last_timestamp = None
        self.last_snapshot = None
        self.load_snapshots()

    def load_snapshots(self):
        """Load snapshots from the file and ensure they are sorted by timestamp."""
        with open(self.snapshots_file_path, 'r') as snapshot_file:
            raw_snapshots = json.load(snapshot_file)

            self.snapshots = sorted([(int(timestamp), snapshot) for timestamp, snapshot in raw_snapshots],
                                    key=lambda x: x[0])

            if len(self.snapshots) > 0:
                self.last_timestamp = self.snapshots[-1][0]
                self.last_snapshot = self.snapshots[-1][1]

    def get_snapshot_by_timestamp(self, query_timestamp):
        """Retrieve a snapshot closest to the given timestamp."""
        timestamps = [ts for ts, _ in self.snapshots]
        idx = bisect.bisect_left(timestamps, query_timestamp)

        if idx == 0:
            return self.snapshots[0]
        elif idx == len(timestamps):
            return self.snapshots[-1]
        else:
            return self.snapshots[idx - 1]

    def add_snapshot(self, timestamp: float, snapshot):
        if self.last_timestamp is not None and timestamp <= self.last_timestamp:
            raise ValueError('timestamp is less than the last timestamp')

        self.last_timestamp = timestamp
        self.last_snapshot = snapshot
        self.snapshots.append((timestamp, snapshot))


class StateManager:
    def __init__(self, nodes_snapshot_timeseries: NodesSnapshotTimeSeries, commitment_interval: float):
        self.nodes_snapshot_timeseries = nodes_snapshot_timeseries
        self.commitment_interval = commitment_interval
        self.nodes_info = {}

    def add_snapshot(self, snapshot):
        self.nodes_info = deep_merge(self.nodes_info, snapshot)

    def run(self):
        while True:
            if self.nodes_snapshot_timeseries.last_snapshot != self.nodes_info:
                self.nodes_snapshot_timeseries.add_snapshot(timestamp=time.time(),
                                                            snapshot=self.nodes_info)
            time.sleep(self.commitment_interval)


# Dependency Injection
def get_state_manager() -> StateManager:
    return state_manager


# Initialize the StateManager and start its daemon thread
snapshots_file_path = NODES_SNAPSHOT_FILE_PATH
commitment_interval = 5  # Example interval in seconds

nodes_snapshot_timeseries = NodesSnapshotTimeSeries(snapshots_file_path)
state_manager = StateManager(nodes_snapshot_timeseries, commitment_interval)

# Start StateManager in a daemon thread
daemon_thread = threading.Thread(target=state_manager.run, daemon=True)
daemon_thread.start()


# Define FastAPI routes
@app.get("/snapshot/{timestamp}")
def get_snapshot(timestamp: int, manager: StateManager = Depends(get_state_manager)):
    """Retrieve the snapshot closest to the given timestamp."""
    try:
        snapshot = manager.nodes_snapshot_timeseries.get_snapshot_by_timestamp(timestamp)
        return {"timestamp": snapshot[0], "snapshot": snapshot[1]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/add_snapshot")
def add_snapshot(snapshot: dict, manager: StateManager = Depends(get_state_manager)):
    """Add a new snapshot."""
    try:
        timestamp = time.time()
        manager.add_snapshot(snapshot)
        return {"message": "Snapshot added successfully.", "timestamp": timestamp}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
