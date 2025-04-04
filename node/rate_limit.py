import math

from limits import RateLimitItemPerSecond
from limits.storage import MemoryStorage
from limits.strategies import MovingWindowRateLimiter

from common.batch import Batch, get_batch_size_kb
from config import zconfig

# Initialize rate limiter storage
storage = MemoryStorage()
limiter = MovingWindowRateLimiter(storage)


def try_acquire_self_node_rate_limit(batches: list[Batch]) -> bool:
    # Todo: use bytes size to avoid use math.ceil
    new_additive_size = math.ceil(sum(get_batch_size_kb(batch) for batch in batches))

    rate_limit = RateLimitItemPerSecond(
        zconfig.node_send_limit_size_kb_per_second,
        zconfig.PUSH_RATE_LIMIT_WINDOW_SECONDS
    )

    return limiter.hit(rate_limit, cost=new_additive_size)
