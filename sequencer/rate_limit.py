from typing import List

from limits import RateLimitItemPerSecond
from limits.storage import MemoryStorage
from limits.strategies import FixedWindowRateLimiter

from common.batch import get_batch_size_kb, Batch
from config import zconfig

# Initialize rate limiter storage
storage = MemoryStorage()
limiter = FixedWindowRateLimiter(storage)

# Define rate limit
rate_limit = RateLimitItemPerSecond(zconfig.node_send_limit_size,
                                    zconfig.PUSH_RATE_LIMIT_WINDOW_SECONDS)


def try_acquire_rate_limit_quota(node_id: str, batches: List[Batch]) -> bool:
    new_additive_size = sum(get_batch_size_kb(batch) for batch in batches)
    key = f"node:{node_id}"

    return limiter.hit(rate_limit, key, cost=new_additive_size)
