from common.rate_limit import MovingWindowRateLimiter
from common.utils import get_utf8_size_kb
from config import zconfig

_limiter = MovingWindowRateLimiter(
    max_cost=zconfig.node_send_limit_per_window_size_kb,
    window_seconds=zconfig.PUSH_RATE_LIMIT_WINDOW_SECONDS,
)

_SELF_NODE_RATE_LIMIT_ID = "self_node_rate_limit"


def try_acquire_rate_limit_of_self_node(batch_bodies: list[str]) -> bool:
    _limiter.update_max_cost(zconfig.node_send_limit_per_window_size_kb)
    cost = sum(get_utf8_size_kb(batch_body) for batch_body in batch_bodies)
    return _limiter.try_acquire(identifier=_SELF_NODE_RATE_LIMIT_ID, cost=cost)


def get_remaining_capacity_kb_of_self_node() -> float:
    return _limiter.get_remaining_capacity(identifier=_SELF_NODE_RATE_LIMIT_ID)
