"""Dashboard reads that span domains (identity keys + llm usage).

"Today" and every date here are Asia/Bangkok (settings.app_tz); storage is
UTC. This is the one place the conversion happens for usage.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.envelope import AppError
from app.services import api_keys, llm_usage

USAGE_RETENTION_DAYS = 60
DEFAULT_RANGE_DAYS = 7

Source = Literal["api", "web"]


@dataclass(frozen=True)
class Totals:
    requests: int
    tokens: int


@dataclass(frozen=True)
class DailyUsage:
    date: date
    requests: int
    tokens: int


@dataclass(frozen=True)
class SourceUsage:
    source: Source
    requests: int
    tokens: int


@dataclass(frozen=True)
class KeyUsage:
    key_id: str
    name: str
    key_prefix: str
    status: str
    requests: int
    tokens: int
    request_share_pct: float


@dataclass(frozen=True)
class Quota:
    limit: int
    used: int
    remaining: int


@dataclass(frozen=True)
class UsageReport:
    date_from: date
    date_to: date
    timezone: str
    clamped: bool
    quota: Quota
    totals: Totals
    by_source: list[SourceUsage]
    by_key: list[KeyUsage]
    daily: list[DailyUsage]


def today(zone: ZoneInfo | None = None) -> date:
    return datetime.now(zone or ZoneInfo(settings.app_tz)).date()


async def usage_report(
    session: AsyncSession,
    *,
    user_id: int,
    date_from: date | None,
    date_to: date | None,
    key_id: str | None,
    days: int | None = None,
    now_date: date | None = None,
) -> UsageReport:
    zone = ZoneInfo(settings.app_tz)
    current = now_date or today(zone)
    requested_to = date_to or current
    # Presets ("last 30 days") are resolved here, not in the browser, so
    # "today" is always Asia/Bangkok's today.
    span = days or DEFAULT_RANGE_DAYS
    requested_from = date_from or requested_to - timedelta(days=span - 1)
    if requested_from > requested_to:
        raise AppError("usage_invalid_range", "`from` must not be after `to`.", 422)

    # Nothing older than retention exists, and nothing after today.
    earliest = current - timedelta(days=USAGE_RETENTION_DAYS - 1)
    start_date = max(requested_from, earliest)
    end_date = min(requested_to, current)
    clamped = (start_date, end_date) != (requested_from, requested_to)
    if start_date > end_date:
        start_date = end_date = current if requested_to > current else earliest

    rows = await llm_usage.hourly_usage(
        session,
        user_id=user_id,
        start=datetime.combine(start_date, time.min, zone),
        end=datetime.combine(end_date + timedelta(days=1), time.min, zone),
        key_id=key_id,
    )

    daily: dict[date, list[int]] = {
        start_date + timedelta(days=offset): [0, 0]
        for offset in range((end_date - start_date).days + 1)
    }
    by_source: dict[str, list[int]] = {"api": [0, 0], "web": [0, 0]}
    by_key: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for row in rows:
        for bucket in (
            daily[row.hour.astimezone(zone).date()],
            by_source[row.source],
            *([by_key[row.key_id]] if row.key_id else []),
        ):
            bucket[0] += row.requests
            bucket[1] += row.tokens

    total_requests = sum(requests for requests, _ in daily.values())
    total_tokens = sum(tokens for _, tokens in daily.values())
    labels = await api_keys.labels(session, user_id, list(by_key))
    limit, used = await llm_usage.quota(session, user_id)

    return UsageReport(
        date_from=start_date,
        date_to=end_date,
        timezone=settings.app_tz,
        clamped=clamped,
        quota=Quota(limit=limit, used=used, remaining=max(limit - used, 0)),
        totals=Totals(requests=total_requests, tokens=total_tokens),
        by_source=[
            SourceUsage(source=source, requests=values[0], tokens=values[1])
            for source, values in by_source.items()
        ],
        by_key=sorted(
            (
                KeyUsage(
                    key_id=kid,
                    name=labels[kid].name if kid in labels else "Unknown key",
                    key_prefix=api_keys.key_prefix(kid),
                    status=labels[kid].status if kid in labels else "deleted",
                    requests=values[0],
                    tokens=values[1],
                    request_share_pct=_share(values[0], total_requests),
                )
                for kid, values in by_key.items()
            ),
            key=lambda usage: (-usage.requests, usage.key_id),
        ),
        daily=[
            DailyUsage(date=day, requests=values[0], tokens=values[1])
            for day, values in daily.items()
        ],
    )


def _share(part: int, whole: int) -> float:
    return round(part * 100 / whole, 1) if whole else 0.0
