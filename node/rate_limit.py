from common.batch import Batch, get_batch_size_kb
from common.rate_limit import MovingWindowRateLimiter
from config import zconfig

_limiter = MovingWindowRateLimiter(max_cost=zconfig.node_send_limit_per_window_size_kb,
                                   window_seconds=zconfig.PUSH_RATE_LIMIT_WINDOW_SECONDS)

_SELF_NODE_RATE_LIMIT_ID = 'self_node_rate_limit'


def try_acquire_self_node_rate_limit(batches: list[Batch]) -> bool:
    _limiter.update_max_cost(zconfig.node_send_limit_per_window_size_kb)
    cost = sum(get_batch_size_kb(batch) for batch in batches)
    return _limiter.try_acquire(identifier=_SELF_NODE_RATE_LIMIT_ID, cost=cost)


def check_capacity(batches: list[Batch]) -> bool:
    _limiter.update_max_cost(zconfig.node_send_limit_per_window_size_kb)
    cost = sum(get_batch_size_kb(batch) for batch in batches)
    return _limiter.check_capacity(identifier=_SELF_NODE_RATE_LIMIT_ID, cost=cost)


def get_node_remaining_capacity_kb() -> int:
    return int(_limiter.get_remaining_capacity(identifier=_SELF_NODE_RATE_LIMIT_ID))
