"""llm_models — the model whitelist.

Not user-owned: the whitelist is global, managed by admins. Names are matched
exactly; there is no prefix, substring or case-insensitive variant.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import UtcDateTime


@dataclass(frozen=True)
class ModelRow:
    id: int
    name: str
    context_window: int
    max_output_tokens: int
    status: str


_utc = UtcDateTime()

# BINARY: the table collation is case-insensitive, and "GPT-4o" must not
# match "gpt-4o" — the whitelist is an exact list.
_GET_BY_NAME = text(
    """
    SELECT id, name, context_window, max_output_tokens, status
    FROM llm_models
    WHERE name = BINARY :name
    """
)


async def get_by_name(session: AsyncSession, *, name: str) -> ModelRow | None:
    row = (await session.execute(_GET_BY_NAME, {"name": name})).mappings().first()
    return ModelRow(**row) if row else None


_GET_BY_ID = text(
    """
    SELECT id, name, context_window, max_output_tokens, status
    FROM llm_models
    WHERE id = :model_id
    """
)


async def get_by_id(session: AsyncSession, *, model_id: int) -> ModelRow | None:
    row = (await session.execute(_GET_BY_ID, {"model_id": model_id})).mappings().first()
    return ModelRow(**row) if row else None


_SET_STATUS = text(
    """
    UPDATE llm_models
    SET status = :status, updated_at = :at
    WHERE id = :model_id
    """
).bindparams(bindparam("at", type_=_utc))


async def set_status(
    session: AsyncSession, *, model_id: int, status: str, at: datetime
) -> bool:
    """True when the model exists (the connection reports matched rows)."""
    result = await session.execute(
        _SET_STATUS, {"model_id": model_id, "status": status, "at": at}
    )
    return result.rowcount == 1


_LIST_ALL = text(
    """
    SELECT id, name, context_window, max_output_tokens, status
    FROM llm_models
    ORDER BY name
    """
)


async def list_all(session: AsyncSession) -> list[ModelRow]:
    """Every model, enabled or not — for admins."""
    rows = await session.execute(_LIST_ALL)
    return [ModelRow(**row) for row in rows.mappings()]


_LIST_ENABLED = text(
    """
    SELECT id, name, context_window, max_output_tokens, status
    FROM llm_models
    WHERE status = 'enabled'
    ORDER BY name
    """
)


async def list_enabled(session: AsyncSession) -> list[ModelRow]:
    """Only the models callers may use — for the public list."""
    rows = await session.execute(_LIST_ENABLED)
    return [ModelRow(**row) for row in rows.mappings()]
