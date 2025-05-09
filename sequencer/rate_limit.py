from common.batch import Batch, get_batch_size_kb
from common.rate_limit import MovingWindowRateLimiter
from config import zconfig

_limiter = MovingWindowRateLimiter(
    max_cost=zconfig.node_send_limit_per_window_size_kb,
    window_seconds=zconfig.PUSH_RATE_LIMIT_WINDOW_SECONDS,
)


def try_acquire_rate_limit_of_other_nodes(node_id: str, batches: list[Batch]) -> bool:
    _limiter.update_max_cost(zconfig.node_send_limit_per_window_size_kb)
    cost = sum(get_batch_size_kb(batch) for batch in batches)
    return _limiter.try_acquire(identifier=node_id, cost=cost)
