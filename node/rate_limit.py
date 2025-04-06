from common.batch import Batch, get_batch_size_kb
from common.rate_limit import DynamicWindowRateLimiter
from config import zconfig

_limiter = DynamicWindowRateLimiter(max_cost_per_second=zconfig.node_send_limit_size_kb_per_second,
                                    window_seconds=zconfig.PUSH_RATE_LIMIT_WINDOW_SECONDS)

_SELF_NODE_RATE_LIMIT = 'self_node_rate_limit'


def try_acquire_self_node_rate_limit(batches: list[Batch]) -> bool:
    cost = sum(get_batch_size_kb(batch) for batch in batches)
    return _limiter.try_acquire(identifier=_SELF_NODE_RATE_LIMIT, cost=cost)


def get_node_remaining_capacity_kb() -> int:
    return int(_limiter.get_remaining_capacity(identifier=_SELF_NODE_RATE_LIMIT))
