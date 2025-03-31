from limits import RateLimitItemPerSecond
from limits.storage import MemoryStorage
from limits.strategies import MovingWindowRateLimiter

from common.batch import get_batch_size_kb, Batch
from config import zconfig

# Initialize rate limiter storage
storage = MemoryStorage()
limiter = MovingWindowRateLimiter(storage)


def try_acquire_rate_limit_quota(node_id: str, batches: list[Batch]) -> bool:
    new_additive_size = int(sum(get_batch_size_kb(batch) for batch in batches))

    # Create a new rate limit dynamically each time
    rate_limit = RateLimitItemPerSecond(
        zconfig.max_node_send_limit_kb_size_per_second,
        zconfig.PUSH_RATE_LIMIT_WINDOW_SECONDS
    )

    return limiter.hit(rate_limit, node_id, cost=new_additive_size)
