import time
from bisect import bisect_left


class DynamicWindowRateLimiter:
    def __init__(self, max_cost_per_second: float, window_seconds: float = 1.0):
        """
        Initialize a dynamic sliding window rate limiter for multiple identifiers.
        """
        self.max_cost = max_cost_per_second * window_seconds
        self.window_seconds = window_seconds
        self.windows: dict[str, list[tuple[float, float]]] = {}
        self.current_sums: dict[str, float] = {}

    def try_acquire(self, identifier: str, cost: float) -> bool:
        """
        Attempt to acquire rate limit for a given identifier and cost.
        """
        remaining = self.get_remaining_capacity(identifier)
        if cost > remaining:
            return False

        # Since get_remaining_capacity already initialized the window if needed,
        # we can directly append the new entry
        current_time = time.perf_counter()
        self.windows[identifier].append((current_time, cost))
        self.current_sums[identifier] += cost
        return True

    def get_remaining_capacity(self, identifier: str) -> float:
        """
        Returns the remaining allowed capacity for an identifier in the last window.
        """
        current_time = time.perf_counter()

        if identifier not in self.windows:
            self.windows[identifier] = []
            self.current_sums[identifier] = 0.0
            return self.max_cost

        window = self.windows[identifier]
        current_sum = self.current_sums[identifier]

        # Find and remove expired items
        expiration_time = current_time - self.window_seconds
        expire_idx = bisect_left(window, expiration_time, key=lambda x: x[0])

        if expire_idx > 0:
            expired = window[:expire_idx]
            window[:] = window[expire_idx:]
            expired_sum = sum(cost for _, cost in expired)
            self.current_sums[identifier] = current_sum - expired_sum
            current_sum = self.current_sums[identifier]

        remaining = self.max_cost - current_sum
        return max(0.0, remaining)
