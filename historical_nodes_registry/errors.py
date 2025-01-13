class SnapshotQueryError(Exception):
    """
    Custom exception raised when a query timestamp is earlier than the first snapshot.
    """

    def __init__(self, query_timestamp: float, first_snapshot_timestamp: float):
        self.query_timestamp = query_timestamp
        self.first_snapshot_timestamp = first_snapshot_timestamp
        message = (
            f"Query timestamp {query_timestamp} is earlier than the first snapshot timestamp "
            f"{first_snapshot_timestamp}."
        )
        super().__init__(message)
