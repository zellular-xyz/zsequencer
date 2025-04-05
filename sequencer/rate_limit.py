from common.batch import Batch, get_batch_size_bytes
from common.rate_limit import DynamicWindowRateLimiter
from config import zconfig

limiter = DynamicWindowRateLimiter(max_cost_per_second=zconfig.node_send_limit_size_bytes_per_second,
                                   window_seconds=zconfig.PUSH_RATE_LIMIT_WINDOW_SECONDS)


def try_acquire_other_nodes_rate_limit_quota(node_id: str, batches: list[Batch]) -> bool:
    cost = sum(get_batch_size_bytes(batch) for batch in batches)
    return limiter.try_acquire(identifier=node_id, cost=cost)
