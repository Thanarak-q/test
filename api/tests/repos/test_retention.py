from datetime import UTC, datetime, timedelta

from sqlalchemy import func, insert, select

from app.jobs.retention import run_retention
from app.models import ApiKeyAuditLog, AuthFailureLog, LlmUsageLog
from tests.repos.helpers import ALICE, seed_key

NOW = datetime(2026, 9, 25, tzinfo=UTC)


async def _count(db, model):
    async with db() as session:
        return await session.scalar(select(func.count()).select_from(model))


async def test_deletes_only_rows_past_each_window_in_batches(db):
    key_id, _ = await seed_key(db, user_id=ALICE)
    async with db.begin() as session:
        for days in (59, 61, 62, 63):  # usage: 60 days
            await session.execute(
                insert(LlmUsageLog).values(
                    user_id=ALICE,
                    source="api",
                    key_id=key_id,
                    model="m",
                    prompt_tokens=1,
                    completion_tokens=1,
                    total_tokens=2,
                    latency_ms=1,
                    created_at=NOW - timedelta(days=days),
                )
            )
        for days in (89, 91):  # audit and auth failures: 90 days
            await session.execute(
                insert(ApiKeyAuditLog).values(
                    user_id=ALICE,
                    action="key.created",
                    actor_type="owner",
                    target_type="api_key",
                    target_id=key_id,
                    created_at=NOW - timedelta(days=days),
                )
            )
            await session.execute(
                insert(AuthFailureLog).values(
                    action="auth.failed",
                    key_id=key_id,
                    source_ip="203.0.113.1",
                    reason="key_not_found",
                    created_at=NOW - timedelta(days=days),
                )
            )

    deleted = await run_retention(db, now=NOW, batch=2)

    assert deleted == {
        "llm_usage_logs": 3,
        "identity_api_key_audit_logs": 1,
        "identity_auth_failure_logs": 1,
    }
    assert await _count(db, LlmUsageLog) == 1
    assert await _count(db, ApiKeyAuditLog) == 1
    assert await _count(db, AuthFailureLog) == 1
