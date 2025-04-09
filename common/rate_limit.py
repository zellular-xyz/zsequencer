import time
from bisect import bisect_left


class MovingWindowRateLimiter:
    def __init__(self, max_cost: float, window_seconds: float = 1.0):
        """
        Initialize a dynamic sliding window rate limiter for multiple identifiers.

        Args:
            max_cost: Maximum allowed cost within the time window
            window_seconds: The duration of the sliding window in seconds
        """
        self._max_cost = max_cost
        self._window_seconds = window_seconds
        self._cost_history_by_id: dict[str, list[tuple[float, float]]] = {}
        self._costs_sum_by_id: dict[str, float] = {}

    def update_max_cost(self, max_cost: float) -> None:
        """
        Update the maximum allowed cost within the time window.

        Args:
            max_cost: New maximum cost value
        """
        self._max_cost = max_cost

    def try_acquire(self, identifier: str, cost: float) -> bool:
        """
        Attempt to acquire rate limit for a given identifier and cost.

        Args:
            identifier: The unique identifier for this rate limit
            cost: The cost of the current operation

        Returns:
            True if the operation is allowed within rate limits, False otherwise
        """
        if cost == 0:
            return True

        if not self.check_capacity(identifier, cost):
            return False

        # Since get_remaining_capacity already initialized the window if needed,
        # we can directly append the new entry
        current_time = time.perf_counter()
        self._cost_history_by_id[identifier].append((current_time, cost))
        self._costs_sum_by_id[identifier] += cost
        return True

    def get_remaining_capacity(self, identifier: str) -> float:
        """
        Returns the remaining allowed capacity for an identifier in the current window.

        Args:
            identifier: The unique identifier to check capacity for

        Returns:
            The remaining cost capacity available within the current time window
        """
        current_time = time.perf_counter()

        if identifier not in self._cost_history_by_id:
            self._cost_history_by_id[identifier] = []
            self._costs_sum_by_id[identifier] = 0.0
            return self._max_cost

        events = self._cost_history_by_id[identifier]

        # Find and remove expired items
        expiration_time = current_time - self._window_seconds
        expire_idx = bisect_left(events, expiration_time, key=lambda x: x[0])

        if expire_idx > 0:
            expired = events[:expire_idx]
            events[:] = events[expire_idx:]
            expired_sum = sum(cost for _, cost in expired)
            self._costs_sum_by_id[identifier] -= expired_sum

        remaining = self._max_cost - self._costs_sum_by_id[identifier]
        return max(0.0, remaining)

    def check_capacity(self, identifier: str, cost: float) -> bool:
        """
        Check if there is enough capacity for the given cost without modifying state.

        Args:
            identifier: The unique identifier to check capacity for
            cost: The cost to check against the available capacity

        Returns:
            True if there is enough capacity, False otherwise
        """
        if cost == 0:
            return True

        return cost <= self.get_remaining_capacity(identifier)
