"""llm_provider_call_logs — one metadata row per provider call.

Never prompt or response content: the columns are the loggable allowlist
(request_id, key_id, model_id, outcome, token counts, latency).
"""

from datetime import datetime

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import UtcDateTime

_utc = UtcDateTime()

_RECORD = text(
    """
    INSERT INTO llm_provider_call_logs
        (user_id, key_id, request_id, model_id, outcome,
         prompt_tokens, completion_tokens, latency_ms, created_at)
    VALUES
        (:user_id, :key_id, :request_id, :model_id, :outcome,
         :prompt_tokens, :completion_tokens, :latency_ms, :at)
    """
).bindparams(bindparam("at", type_=_utc))


async def record(
    session: AsyncSession,
    *,
    user_id: int,
    key_id: str,
    request_id: str,
    model_id: int,
    outcome: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    latency_ms: int,
    at: datetime,
) -> None:
    await session.execute(
        _RECORD,
        {
            "user_id": user_id,
            "key_id": key_id,
            "request_id": request_id,
            "model_id": model_id,
            "outcome": outcome,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "latency_ms": latency_ms,
            "at": at,
        },
    )


_DELETE_BEFORE = text(
    """
    DELETE FROM llm_provider_call_logs
    WHERE created_at < :before
    ORDER BY created_at
    LIMIT :batch
    """
).bindparams(bindparam("before", type_=_utc))


async def delete_before(session: AsyncSession, *, before: datetime, batch: int) -> int:
    """Retention: delete up to `batch` rows older than `before`."""
    result = await session.execute(_DELETE_BEFORE, {"before": before, "batch": batch})
    return result.rowcount
