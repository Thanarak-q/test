"""identity_api_keys and its identity_users lock row.

Every function takes user_id as a required keyword and filters on it in the
WHERE clause (docs/NON_FUNCTIONAL.md §1.1). The single exception is
get_for_auth: it runs before the caller is known, because the key record is
where the caller's user_id comes from.

key_hash is selected by get_for_auth only; no other function reads it, so no
management response can carry it.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import UtcDateTime


@dataclass(frozen=True)
class AuthRecordRow:
    key_id: str
    user_id: int
    key_hash: str
    status: str
    last_used_at: datetime | None


@dataclass(frozen=True)
class ApiKeyRow:
    id: str
    name: str
    status: str
    created_at: datetime
    last_used_at: datetime | None


@dataclass(frozen=True)
class KeyLabelRow:
    id: str
    name: str
    status: str


_utc = UtcDateTime()

_GET_FOR_AUTH = text(
    """
    SELECT id AS key_id, user_id, key_hash, status, last_used_at
    FROM identity_api_keys
    WHERE id = :key_id
    """
).columns(last_used_at=_utc)


async def get_for_auth(session: AsyncSession, *, key_id: str) -> AuthRecordRow | None:
    """The key's auth record, whoever owns it. Auth lookups only."""
    row = (await session.execute(_GET_FOR_AUTH, {"key_id": key_id})).mappings().first()
    return AuthRecordRow(**row) if row else None


_TOUCH_LAST_USED = text(
    """
    UPDATE identity_api_keys
    SET last_used_at = :at
    WHERE id = :key_id AND user_id = :user_id
    """
).bindparams(bindparam("at", type_=_utc))


async def touch_last_used(
    session: AsyncSession, *, key_id: str, user_id: int, at: datetime
) -> bool:
    result = await session.execute(
        _TOUCH_LAST_USED, {"key_id": key_id, "user_id": user_id, "at": at}
    )
    return result.rowcount == 1


_LOCK_USER = text(
    """
    INSERT INTO identity_users (id) VALUES (:user_id)
    ON DUPLICATE KEY UPDATE id = id
    """
)


async def lock_user(session: AsyncSession, *, user_id: int) -> None:
    """Create the user's mirror row if needed and hold its lock until commit.

    Serialises key creation per user. Without it, two concurrent conditional
    inserts each take shared gap locks and then deadlock on each other's
    (MySQL error 1213 — reproduced by the concurrency test).
    """
    await session.execute(_LOCK_USER, {"user_id": user_id})


# One statement: the count and the insert cannot be separated by another
# transaction's insert, so the limit holds under concurrency.
_INSERT_IF_UNDER_LIMIT = text(
    """
    INSERT INTO identity_api_keys (id, user_id, name, key_hash, status, created_at)
    SELECT :key_id, :user_id, :name, :key_hash, 'active', :created_at FROM DUAL
    WHERE (
        SELECT COUNT(*) FROM identity_api_keys
        WHERE user_id = :user_id AND status = 'active'
    ) < :max_active
    """
).bindparams(bindparam("created_at", type_=_utc))


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
            "key_id": key_id,
            "user_id": user_id,
            "name": name,
            "key_hash": key_hash,
            "created_at": created_at,
            "max_active": max_active,
        },
    )
    return result.rowcount == 1


_LIST_FOR_USER = text(
    """
    SELECT id, name, status, created_at, last_used_at
    FROM identity_api_keys
    WHERE user_id = :user_id AND status != 'deleted'
    ORDER BY created_at DESC, id DESC
    """
).columns(created_at=_utc, last_used_at=_utc)


async def list_for_user(session: AsyncSession, *, user_id: int) -> list[ApiKeyRow]:
    """The user's keys that are not deleted, newest first."""
    rows = await session.execute(_LIST_FOR_USER, {"user_id": user_id})
    return [ApiKeyRow(**row) for row in rows.mappings()]


_GET_STATUS = text(
    """
    SELECT status FROM identity_api_keys
    WHERE id = :key_id AND user_id = :user_id
    """
)


async def get_status(session: AsyncSession, *, key_id: str, user_id: int) -> str | None:
    """The key's status if it is the user's, else None."""
    return await session.scalar(_GET_STATUS, {"key_id": key_id, "user_id": user_id})


_REVOKE = text(
    """
    UPDATE identity_api_keys
    SET status = 'revoked', revoked_at = COALESCE(revoked_at, :at)
    WHERE id = :key_id AND user_id = :user_id AND status = 'active'
    """
).bindparams(bindparam("at", type_=_utc))


async def revoke(
    session: AsyncSession, *, key_id: str, user_id: int, at: datetime
) -> bool:
    """True only when this call moved the user's key from active to revoked."""
    result = await session.execute(
        _REVOKE, {"key_id": key_id, "user_id": user_id, "at": at}
    )
    return result.rowcount == 1


_SOFT_DELETE = text(
    """
    UPDATE identity_api_keys
    SET status = 'deleted', deleted_at = COALESCE(deleted_at, :at)
    WHERE id = :key_id AND user_id = :user_id AND status != 'deleted'
    """
).bindparams(bindparam("at", type_=_utc))


async def soft_delete(
    session: AsyncSession, *, key_id: str, user_id: int, at: datetime
) -> bool:
    """True only when this call moved the user's key to deleted."""
    result = await session.execute(
        _SOFT_DELETE, {"key_id": key_id, "user_id": user_id, "at": at}
    )
    return result.rowcount == 1


_LABELS_FOR_USER = text(
    """
    SELECT id, name, status FROM identity_api_keys
    WHERE user_id = :user_id AND id IN :key_ids
    """
).bindparams(bindparam("key_ids", expanding=True))


async def labels_for_user(
    session: AsyncSession, *, user_id: int, key_ids: list[str]
) -> list[KeyLabelRow]:
    """Name and status of the user's keys among key_ids, deleted ones included
    (usage outlives a key). Ids that are not the user's are simply absent."""
    if not key_ids:
        return []
    rows = await session.execute(
        _LABELS_FOR_USER, {"user_id": user_id, "key_ids": key_ids}
    )
    return [KeyLabelRow(**row) for row in rows.mappings()]


# Retention (app/jobs/retention.py, its own DB user): a soft-deleted key keeps
# its row for the audit trail, then is purged. Not user-scoped by design —
# it runs across all users and touches only rows already marked deleted.
_PURGE_DELETED_BEFORE = text(
    """
    DELETE FROM identity_api_keys
    WHERE status = 'deleted' AND deleted_at < :before
    ORDER BY deleted_at
    LIMIT :batch
    """
).bindparams(bindparam("before", type_=_utc))


async def purge_deleted_before(
    session: AsyncSession, *, before: datetime, batch: int
) -> int:
    result = await session.execute(
        _PURGE_DELETED_BEFORE, {"before": before, "batch": batch}
    )
    return result.rowcount
