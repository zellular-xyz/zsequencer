import time
from bisect import bisect_left


class DynamicWindowRateLimiter:
    def __init__(self, max_cost_per_second: float, window_seconds: float = 1.0):
        """
        Initialize a dynamic sliding window rate limiter for multiple identifiers.

        Args:
            max_cost_per_second: Maximum allowed cost (e.g., bytes) per second per identifier.
            window_seconds: Time window in seconds for rate limiting (default: 1.0).
        """
        self.max_cost = max_cost_per_second * window_seconds
        self.window_seconds = window_seconds
        # Dictionary mapping identifier to list of (timestamp, cost) pairs, sorted by timestamp
        self.windows: dict[str, list[tuple[float, float]]] = {}
        # Dictionary tracking current sum for each identifier
        self.current_sums: dict[str, float] = {}

    def try_acquire(self, identifier: str, cost: float) -> bool:
        """
        Attempt to acquire rate limit for a given identifier and cost.

        Args:
            identifier: Unique identifier for the entity being rate-limited (e.g., node ID).
            cost: The cost value (e.g., bytes) to be added.

        Returns:
            bool: True if rate limit allows, False if limit would be exceeded.
        """
        current_time = time.time()

        # Initialize window and sum for new identifiers
        if identifier not in self.windows:
            self.windows[identifier] = []
            self.current_sums[identifier] = 0.0

        window = self.windows[identifier]
        current_sum = self.current_sums[identifier]

        # Find the index of the first non-expired item using binary search
        expiration_time = current_time - self.window_seconds
        expire_idx = bisect_left(window, expiration_time, key=lambda x: x[0])

        # Remove expired items and update sum
        if expire_idx > 0:
            expired = window[:expire_idx]
            window[:] = window[expire_idx:]
            expired_sum = sum(cost for _, cost in expired)
            self.current_sums[identifier] = current_sum - expired_sum

        # Check if adding the new cost exceeds the limit
        if self.current_sums[identifier] + cost > self.max_cost:
            return False

        # Acquire the limit by adding the new entry
        window.append((current_time, cost))
        self.current_sums[identifier] += cost
        return True