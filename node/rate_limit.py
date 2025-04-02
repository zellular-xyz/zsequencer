from limits import RateLimitItemPerSecond
from limits.storage import MemoryStorage
from limits.strategies import FixedWindowRateLimiter

from common.batch import Batch, get_batch_size_bytes
from config import zconfig

# Initialize rate limiter storage
storage = MemoryStorage()
limiter = FixedWindowRateLimiter(storage)


def try_acquire_self_node_rate_limit(batches: list[Batch]) -> bool:
    new_additive_size = sum(get_batch_size_bytes(batch) for batch in batches)

    rate_limit = RateLimitItemPerSecond(
        zconfig.node_send_limit_size_bytes_per_second,
        zconfig.PUSH_RATE_LIMIT_WINDOW_SECONDS
    )

    return limiter.hit(rate_limit, cost=new_additive_size)
