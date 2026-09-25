"""llm_usage_logs — tokens charged against quota, per request.

Written after quota_reconcile; read by the dashboard. Metadata only: no
model, no source IP, no content.
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
           COALESCE(SUM(tokens), 0) AS tokens
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


_RECORD = text(
    """
    INSERT INTO llm_usage_logs (user_id, source, key_id, tokens, request_id, created_at)
    VALUES (:user_id, :source, :key_id, :tokens, :request_id, :at)
    """
).bindparams(bindparam("at", type_=_utc))


async def record(
    session: AsyncSession,
    *,
    user_id: int,
    source: str,
    key_id: str | None,
    tokens: int,
    request_id: str | None,
    at: datetime,
) -> None:
    await session.execute(
        _RECORD,
        {
            "user_id": user_id,
            "source": source,
            "key_id": key_id,
            "tokens": tokens,
            "request_id": request_id,
            "at": at,
        },
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
