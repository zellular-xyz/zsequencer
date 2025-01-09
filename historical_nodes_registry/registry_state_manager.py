import bisect
import copy
import threading
import time
from typing import Dict, Optional, List, Tuple

from historical_nodes_registry.schema import NodeInfo, SnapShotType


class RegistryStateManager:
    """Manages a time series of node snapshots and the current state of nodes."""

    def __init__(self, logger):
        self._snapshots: List[Tuple[float, SnapShotType]] = []
        self._last_timestamp: Optional[float] = None
        self._last_snapshot: Optional[SnapShotType] = None
        self._logger = logger
        self._lock = threading.Lock()

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

    def get_snapshot_by_timestamp(self, query_timestamp: Optional[float]) -> Tuple[float, SnapShotType]:
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
            return query_timestamp, {}
        return self._snapshots[idx]

    def add_snapshot(self, snapshot: SnapShotType):
        if snapshot != self._last_snapshot:
            with self._lock:
                now_timestamp = time.time()
                self._last_timestamp, self._last_snapshot, self._snapshots = (snapshot
                                                                              , now_timestamp
                                                                              , [*self._snapshots,
                                                                                 (now_timestamp, snapshot)])

    def update_node_info(self, node_info: NodeInfo):
        last_snapshot_copy = copy.deepcopy(self._snapshots)
        last_snapshot_copy = {node_info.id: node_info} if last_snapshot_copy is None else {**last_snapshot_copy,
                                                                                           node_info.id: node_info}
        self.add_snapshot(last_snapshot_copy)
