"""Delete logs older than their retention window.

    uv run --directory api python -m app.jobs.retention

Run it from cron (daily is enough) as a DB user that holds DELETE on the log
tables — the app's own user does not (docs/DB_PERMISSIONS.md). Deletes run in
small batches, each its own transaction, so the job never holds locks the
request path is waiting for and can be stopped and rerun at any point.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.constants.retention import (
    AUDIT_RETENTION_DAYS,
    AUTH_FAILURE_RETENTION_DAYS,
    RETENTION_DELETE_BATCH,
    USAGE_RETENTION_DAYS,
)
from app.repos import audit_repo, usage_repo

logger = logging.getLogger(__name__)

DeleteBatch = Callable[..., Awaitable[int]]

POLICIES: tuple[tuple[str, DeleteBatch, int], ...] = (
    ("llm_usage_logs", usage_repo.delete_before, USAGE_RETENTION_DAYS),
    (
        "identity_api_key_audit_logs",
        audit_repo.delete_key_events_before,
        AUDIT_RETENTION_DAYS,
    ),
    (
        "identity_auth_failure_logs",
        audit_repo.delete_auth_failures_before,
        AUTH_FAILURE_RETENTION_DAYS,
    ),
)


async def run_retention(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime | None = None,
    batch: int = RETENTION_DELETE_BATCH,
) -> dict[str, int]:
    """Delete everything past retention; returns rows deleted per table."""
    current = now or datetime.now(UTC)
    deleted: dict[str, int] = {}
    for table, delete_batch, days in POLICIES:
        before = current - timedelta(days=days)
        total = 0
        while True:
            async with session_factory.begin() as session:
                count = await delete_batch(session, before=before, batch=batch)
            total += count
            if count < batch:
                break
        deleted[table] = total
        logger.info("retention: %s deleted %d rows before %s", table, total, before)
    return deleted


def main() -> None:
    from app.db import SessionLocal, engine

    logging.basicConfig(level=logging.INFO)

    async def run() -> None:
        try:
            await run_retention(SessionLocal)
        finally:
            await engine.dispose()

    asyncio.run(run())


if __name__ == "__main__":
    main()
