from limits import RateLimitItemPerSecond
from limits.storage import MemoryStorage
from limits.strategies import MovingWindowRateLimiter

from common.batch import get_batch_size_kb, Batch
from config import zconfig

# Initialize rate limiter storage
storage = MemoryStorage()
limiter = MovingWindowRateLimiter(storage)


def try_acquire_node_rate_limit_quota(batches: list[Batch]) -> bool:
    new_additive_size = int(sum(get_batch_size_kb(batch) for batch in batches))

    rate_limit = RateLimitItemPerSecond(
        zconfig.max_node_send_limit_size_per_second,
        zconfig.PUSH_RATE_LIMIT_WINDOW_SECONDS
    )

    return limiter.hit(rate_limit, cost=new_additive_size)
