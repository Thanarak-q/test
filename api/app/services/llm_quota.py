"""Quota with reservation.

Checking usage before the call and writing it after is a race: N concurrent
requests all read the same pre-call total and all pass. So the pipeline reserves
an estimate up front (atomic INCRBY, rejected and rolled back if it breaks the
limit), then reconciles with the provider's real token count.

Redis holds `spent` = settled usage + outstanding reservations. MySQL holds the
settled total and is the source of truth: the counter is seeded from it whenever
the key is missing, so a flushed Redis reloads rather than resetting to zero.
"""

from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.envelope import AppError
from app.repos import llm as llm_repo


@dataclass(frozen=True)
class Reservation:
    user_id: int
    estimate: int
    limit: int


def _key(user_id: int) -> str:
    return f"llm:quota:{user_id}:spent"


async def reserve(
    redis: Redis, session: AsyncSession, user_id: int, estimate: int
) -> Reservation:
    quota = await llm_repo.get_quota(session, user_id)
    limit = quota.token_limit if quota else settings.llm_token_quota
    settled = quota.token_used if quota else 0

    key = _key(user_id)
    # Seeds from the DB only when the counter is absent; a live counter carrying
    # other requests' reservations must never be overwritten.
    await redis.set(key, settled, nx=True)

    spent = await redis.incrby(key, estimate)
    if spent > limit:
        await redis.decrby(key, estimate)
        raise AppError(
            "llm_quota_exceeded",
            f"Token quota exceeded ({spent - estimate}/{limit}).",
            status_code=403,
        )
    return Reservation(user_id=user_id, estimate=estimate, limit=limit)


async def release(redis: Redis, reservation: Reservation) -> None:
    """Give the reservation back — the call never consumed anything."""
    await redis.decrby(_key(reservation.user_id), reservation.estimate)


async def settle(
    redis: Redis, session: AsyncSession, reservation: Reservation, actual: int
) -> None:
    """Swap the estimate for the real count and persist the settled total."""
    await redis.incrby(_key(reservation.user_id), actual - reservation.estimate)
    await llm_repo.add_token_usage(
        session, reservation.user_id, actual, reservation.limit
    )
