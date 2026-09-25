"""The llm domain's read API for other modules.

The dashboard reads usage through here rather than through app/repos/usage_repo
directly: modules call each other's services, never each other's repos.
"""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.repos import usage_repo
from app.repos.usage_repo import HourlyUsage

__all__ = ["HourlyUsage", "hourly_usage"]


async def hourly_usage(
    session: AsyncSession,
    *,
    user_id: int,
    start: datetime,
    end: datetime,
    key_id: str | None,
) -> list[HourlyUsage]:
    return await usage_repo.hourly_for_user(
        session, user_id=user_id, start=start, end=end, key_id=key_id
    )
