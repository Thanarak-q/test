"""Per-user rate limit on key management (docs/planning/chat_pipeline.md).

Two buckets per user: reads (list) get a higher cap than writes (create,
revoke, delete), which mint secrets and audit rows. Fails closed like every
other limiter: Redis down is a 503.
"""

from typing import Literal

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.constants.mgmt_rate_limit import (
    BUCKET_TTL_SECONDS,
    READ_CAPACITY,
    READ_REFILL_PER_SECOND,
    WRITE_CAPACITY,
    WRITE_REFILL_PER_SECOND,
)
from app.envelope import AppError
from app.services.pre_auth_rate_limit import TOKEN_BUCKET_LUA

Kind = Literal["read", "write"]

_POLICY = {
    "read": (READ_CAPACITY, READ_REFILL_PER_SECOND),
    "write": (WRITE_CAPACITY, WRITE_REFILL_PER_SECOND),
}


def bucket_key(user_id: int, kind: Kind) -> str:
    return f"rl:mgmt:{kind}:{user_id}"


async def mgmt_rate_limit(redis: Redis, *, user_id: int, kind: Kind) -> None:
    capacity, refill = _POLICY[kind]
    try:
        allowed, _remaining, retry_after, _reset = await redis.eval(
            TOKEN_BUCKET_LUA,
            1,
            bucket_key(user_id, kind),
            capacity,
            refill,
            BUCKET_TTL_SECONDS,
            1,
        )
    except RedisError as exc:
        raise AppError(
            "service_unavailable",
            "The service is temporarily unavailable. Try again shortly.",
            503,
        ) from exc
    if int(allowed) == 0:
        retry = max(int(retry_after), 1)
        raise AppError(
            "identity_rate_limit_exceeded",
            f"Too many requests. Retry in {retry}s.",
            429,
            headers={"Retry-After": str(retry)},
        )
