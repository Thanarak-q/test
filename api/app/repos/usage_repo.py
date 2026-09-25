"""Read side of llm_usage_logs and llm_quotas, plus usage retention.

TODO(chat-pipeline): the chat pipeline owns these tables and writes them.
The columns read here (source, key_id, total_tokens, created_at; token_limit,
token_used) are the shape proposed in the phase 1 migration — confirm with the
pipeline owner.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import UtcDateTime


@dataclass(frozen=True)
class HourlyUsage:
    hour: datetime  # UTC, aware, truncated to the hour
    source: str
    key_id: str | None
    requests: int
    tokens: int


@dataclass(frozen=True)
class QuotaRow:
    token_limit: int
    token_used: int


_utc = UtcDateTime()

# Grouped by UTC hour rather than date, so the caller can bucket into the
# user's local day without SQL knowing about zones. The format string is a
# bound parameter like every other value.
_HOURLY_FOR_USER = text(
    """
    SELECT DATE_FORMAT(created_at, :hour_format) AS hour,
           source,
           key_id,
           COUNT(*) AS requests,
           COALESCE(SUM(total_tokens), 0) AS tokens
    FROM llm_usage_logs
    WHERE user_id = :user_id
      AND created_at >= :start
      AND created_at < :end
      AND (:key_id IS NULL OR key_id = :key_id)
    GROUP BY hour, source, key_id
    """
).bindparams(bindparam("start", type_=_utc), bindparam("end", type_=_utc))


async def hourly_for_user(
    session: AsyncSession,
    *,
    user_id: int,
    start: datetime,
    end: datetime,
    key_id: str | None,
) -> list[HourlyUsage]:
    """The user's usage in [start, end), per UTC hour, source and key."""
    rows = await session.execute(
        _HOURLY_FOR_USER,
        {
            "hour_format": "%Y-%m-%d %H:00:00",
            "user_id": user_id,
            "start": start,
            "end": end,
            "key_id": key_id,
        },
    )
    return [
        HourlyUsage(
            hour=datetime.fromisoformat(row["hour"]).replace(tzinfo=UTC),
            source=row["source"],
            key_id=row["key_id"],
            requests=int(row["requests"]),
            tokens=int(row["tokens"]),
        )
        for row in rows.mappings()
    ]


_GET_QUOTA = text(
    """
    SELECT token_limit, token_used FROM llm_quotas
    WHERE user_id = :user_id
    """
)


async def get_quota(session: AsyncSession, *, user_id: int) -> QuotaRow | None:
    """The user's quota as settled in MySQL, or None if no row yet."""
    row = (await session.execute(_GET_QUOTA, {"user_id": user_id})).mappings().first()
    return (
        QuotaRow(token_limit=int(row["token_limit"]), token_used=int(row["token_used"]))
        if row
        else None
    )


_DELETE_BEFORE = text(
    """
    DELETE FROM llm_usage_logs
    WHERE created_at < :before
    ORDER BY created_at
    LIMIT :batch
    """
).bindparams(bindparam("before", type_=_utc))


async def delete_before(session: AsyncSession, *, before: datetime, batch: int) -> int:
    """Retention: delete up to `batch` rows older than `before`."""
    result = await session.execute(_DELETE_BEFORE, {"before": before, "batch": batch})
    return result.rowcount
