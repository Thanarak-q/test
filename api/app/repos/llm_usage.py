"""Read side of llm_usage_logs and llm_quotas for the dashboard.

TODO(chat-pipeline): the chat pipeline owns these tables and writes them.
The columns read here (source, key_id, total_tokens, created_at; token_limit,
token_used) are the shape proposed in the phase 1 migration — confirm with the
pipeline owner.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LlmQuota, LlmUsageLog


@dataclass(frozen=True)
class HourlyUsage:
    hour: datetime  # UTC, aware, truncated to the hour
    source: str
    key_id: str | None
    requests: int
    tokens: int


async def hourly_usage(
    session: AsyncSession,
    *,
    user_id: int,
    start: datetime,
    end: datetime,
    key_id: str | None,
) -> list[HourlyUsage]:
    """Usage in [start, end), grouped by UTC hour, source and key.

    Grouped by hour rather than date so the caller can bucket into the
    user's local day without SQL knowing about zones.
    """
    hour = func.date_format(LlmUsageLog.created_at, "%Y-%m-%d %H:00:00")
    statement = (
        select(
            hour.label("hour"),
            LlmUsageLog.source,
            LlmUsageLog.key_id,
            func.count().label("requests"),
            func.coalesce(func.sum(LlmUsageLog.total_tokens), 0).label("tokens"),
        )
        .where(
            LlmUsageLog.user_id == user_id,
            LlmUsageLog.created_at >= start,
            LlmUsageLog.created_at < end,
        )
        .group_by(hour, LlmUsageLog.source, LlmUsageLog.key_id)
    )
    if key_id is not None:
        statement = statement.where(LlmUsageLog.key_id == key_id)

    return [
        HourlyUsage(
            hour=datetime.fromisoformat(row.hour).replace(tzinfo=UTC),
            source=row.source,
            key_id=row.key_id,
            requests=int(row.requests),
            tokens=int(row.tokens),
        )
        for row in await session.execute(statement)
    ]


async def get_quota(session: AsyncSession, user_id: int) -> tuple[int, int] | None:
    """(token_limit, token_used) as settled in MySQL, or None if no row yet."""
    row = (
        await session.execute(
            select(LlmQuota.token_limit, LlmQuota.token_used).where(
                LlmQuota.user_id == user_id
            )
        )
    ).one_or_none()
    return None if row is None else (int(row.token_limit), int(row.token_used))
