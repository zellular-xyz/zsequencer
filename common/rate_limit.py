import time
from bisect import bisect_left
from collections import defaultdict
from threading import Lock


class DynamicWindowRateLimiter:
    def __init__(self, max_cost: float, window_seconds: float = 1.0):
        self._max_cost = max_cost
        self._window_seconds = window_seconds
        self._windows: dict[str, list[tuple[float, float]]] = {}
        self._current_sums: dict[str, float] = {}
        self._locks = defaultdict(Lock)
        self._max_cost_lock = Lock()

    def update_max_cost(self, max_cost: float):
        with self._max_cost_lock:
            self._max_cost = max_cost

    def try_acquire(self, identifier: str, cost: float) -> bool:
        with self._locks[identifier]:
            remaining = self.get_remaining_capacity(identifier)
            if cost > remaining:
                return False
            current_time = time.perf_counter()
            self._windows[identifier].append((current_time, cost))
            self._current_sums[identifier] += cost
            return True

    def get_remaining_capacity(self, identifier: str) -> float:
        with self._locks[identifier]:
            current_time = time.perf_counter()
            if identifier not in self._windows:
                self._windows[identifier] = []
                self._current_sums[identifier] = 0.0
                with self._max_cost_lock:
                    return self._max_cost

            window = self._windows[identifier]
            expiration_time = current_time - self._window_seconds
            expire_idx = bisect_left(window, expiration_time, key=lambda x: x[0])

            if expire_idx > 0:
                expired = window[:expire_idx]
                window[:] = window[expire_idx:]
                expired_sum = sum(cost for _, cost in expired)
                self._current_sums[identifier] -= expired_sum

            with self._max_cost_lock:
                remaining = self._max_cost - self._current_sums[identifier]
            return max(0.0, remaining)
