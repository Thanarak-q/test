"""identity_api_keys. Every query is scoped by user_id in its WHERE clause.

The single exception is get_auth_record: it runs before the caller is known,
because the key record is where the caller's user_id comes from.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import bindparam, func, literal, select, text, update
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import UtcDateTime
from app.models import ApiKey, User


@dataclass(frozen=True)
class ApiKeyRow:
    """What the management API may read. key_hash is not selected at all."""

    id: str
    name: str
    status: str
    created_at: datetime
    last_used_at: datetime | None


async def get_auth_record(
    session: AsyncSession, key_id: str
) -> dict[str, object] | None:
    row = (
        await session.execute(
            select(
                ApiKey.id,
                ApiKey.user_id,
                ApiKey.key_hash,
                ApiKey.status,
                ApiKey.last_used_at,
            ).where(ApiKey.id == key_id)
        )
    ).one_or_none()
    if row is None:
        return None
    return {
        "key_id": row.id,
        "user_id": row.user_id,
        "key_hash": row.key_hash,
        "status": row.status,
        "last_used_at": row.last_used_at,
    }


async def touch_last_used(
    session: AsyncSession, *, key_id: str, user_id: int, at: datetime
) -> None:
    await session.execute(
        update(ApiKey)
        .where(ApiKey.id == key_id, ApiKey.user_id == user_id)
        .values(last_used_at=at)
    )


async def lock_user(session: AsyncSession, user_id: int) -> None:
    """Create the user's row if needed and hold its row lock until commit.

    Serialises key creation per user. Without it, two concurrent conditional
    inserts each take shared gap locks and then deadlock on each other's.
    """
    statement = mysql_insert(User).values(id=user_id)
    await session.execute(statement.on_duplicate_key_update(id=statement.inserted.id))


# One statement: the count and the insert cannot be separated by another
# transaction's insert, so the limit holds under concurrency.
_INSERT_IF_UNDER_LIMIT = text(
    """
    INSERT INTO identity_api_keys (id, user_id, name, key_hash, status, created_at)
    SELECT :id, :user_id, :name, :key_hash, 'active', :created_at FROM DUAL
    WHERE (
        SELECT COUNT(*) FROM identity_api_keys
        WHERE user_id = :user_id AND status = 'active'
    ) < :max_active
    """
).bindparams(bindparam("created_at", type_=UtcDateTime()))


async def insert_if_under_limit(
    session: AsyncSession,
    *,
    key_id: str,
    user_id: int,
    name: str,
    key_hash: str,
    created_at: datetime,
    max_active: int,
) -> bool:
    result = await session.execute(
        _INSERT_IF_UNDER_LIMIT,
        {
            "id": key_id,
            "user_id": user_id,
            "name": name,
            "key_hash": key_hash,
            "created_at": created_at,
            "max_active": max_active,
        },
    )
    return result.rowcount == 1


async def list_for_user(session: AsyncSession, user_id: int) -> list[ApiKeyRow]:
    rows = await session.execute(
        select(
            ApiKey.id,
            ApiKey.name,
            ApiKey.status,
            ApiKey.created_at,
            ApiKey.last_used_at,
        )
        .where(ApiKey.user_id == user_id, ApiKey.status != "deleted")
        .order_by(ApiKey.created_at.desc(), ApiKey.id.desc())
    )
    return [ApiKeyRow(**row._mapping) for row in rows]


async def get_status(session: AsyncSession, *, key_id: str, user_id: int) -> str | None:
    return await session.scalar(
        select(ApiKey.status).where(ApiKey.id == key_id, ApiKey.user_id == user_id)
    )


async def revoke(
    session: AsyncSession, *, key_id: str, user_id: int, at: datetime
) -> bool:
    """Returns True only when this call moved the key from active to revoked."""
    result = await session.execute(
        update(ApiKey)
        .where(
            ApiKey.id == key_id,
            ApiKey.user_id == user_id,
            ApiKey.status == "active",
        )
        .values(status="revoked", revoked_at=_coalesce(ApiKey.revoked_at, at))
    )
    return result.rowcount == 1


async def soft_delete(
    session: AsyncSession, *, key_id: str, user_id: int, at: datetime
) -> bool:
    """Returns True only when this call moved the key to deleted."""
    result = await session.execute(
        update(ApiKey)
        .where(
            ApiKey.id == key_id,
            ApiKey.user_id == user_id,
            ApiKey.status != "deleted",
        )
        .values(status="deleted", deleted_at=_coalesce(ApiKey.deleted_at, at))
    )
    return result.rowcount == 1


def _coalesce(column, at: datetime):
    return func.coalesce(column, literal(at, UtcDateTime()))


@dataclass(frozen=True)
class KeyLabel:
    id: str
    name: str
    status: str


async def labels_for_user(
    session: AsyncSession, *, user_id: int, key_ids: list[str]
) -> list[KeyLabel]:
    """Name and status of the given keys, deleted ones included (usage outlives
    a key). Keys that are not the user's are simply absent."""
    if not key_ids:
        return []
    rows = await session.execute(
        select(ApiKey.id, ApiKey.name, ApiKey.status).where(
            ApiKey.user_id == user_id, ApiKey.id.in_(key_ids)
        )
    )
    return [KeyLabel(**row._mapping) for row in rows]
