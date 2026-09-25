"""The llm domain's read API for other modules.

The dashboard reads usage through here rather than through app/repos/llm_usage
directly: modules call each other's services, never each other's repos.
"""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.repos import llm_usage
from app.repos.llm_usage import HourlyUsage

__all__ = ["HourlyUsage", "hourly_usage", "quota"]


async def hourly_usage(
    session: AsyncSession,
    *,
    user_id: int,
    start: datetime,
    end: datetime,
    key_id: str | None,
) -> list[HourlyUsage]:
    return await llm_usage.hourly_usage(
        session, user_id=user_id, start=start, end=end, key_id=key_id
    )


async def quota(session: AsyncSession, user_id: int) -> tuple[int, int]:
    """(limit, used) for the user's token quota.

    TODO(chat-pipeline): open question 2 — if the pipeline keeps in-flight
    reservations in Redis, MySQL token_used lags them and this should read
    the pipeline's own figure instead. A user without a quota row has used
    nothing against the default limit.
    """
    return await llm_usage.get_quota(session, user_id) or (settings.llm_token_quota, 0)
