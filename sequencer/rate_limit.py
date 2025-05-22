from common.api_models import BatchData
from common.rate_limit import MovingWindowRateLimiter
from common.utils import get_utf8_size_kb
from config import zconfig

_limiter = MovingWindowRateLimiter(
    max_cost=zconfig.node_send_limit_per_window_size_kb,
    window_seconds=zconfig.PUSH_RATE_LIMIT_WINDOW_SECONDS,
)


def try_acquire_rate_limit_of_other_nodes(
    node_id: str, batches: list[BatchData]
) -> bool:
    _limiter.update_max_cost(zconfig.node_send_limit_per_window_size_kb)
    cost = sum(get_utf8_size_kb(batch.body) for batch in batches)
    return _limiter.try_acquire(identifier=node_id, cost=cost)
