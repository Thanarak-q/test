"""SQLAlchemy for the chat pipeline. Callers own the transaction — no commits here."""

from sqlalchemy import insert, select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LlmModel, LlmQuota, LlmUsageLog


async def list_active_models(session: AsyncSession) -> list[str]:
    rows = await session.execute(
        select(LlmModel.model_id).where(LlmModel.is_active.is_(True))
    )
    return list(rows.scalars())


async def get_quota(session: AsyncSession, user_id: int) -> LlmQuota | None:
    rows = await session.execute(select(LlmQuota).where(LlmQuota.user_id == user_id))
    return rows.scalars().first()


async def add_token_usage(
    session: AsyncSession, user_id: int, tokens: int, token_limit: int
) -> None:
    stmt = mysql_insert(LlmQuota).values(
        user_id=user_id, token_limit=token_limit, token_used=tokens
    )
    await session.execute(
        stmt.on_duplicate_key_update(token_used=LlmQuota.token_used + tokens)
    )


async def insert_usage_log(
    session: AsyncSession,
    *,
    user_id: int,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    latency_ms: int,
) -> None:
    await session.execute(
        insert(LlmUsageLog).values(
            user_id=user_id,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
        )
    )
