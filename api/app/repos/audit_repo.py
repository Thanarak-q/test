"""Append-only audit tables. INSERT only — see docs/DB_PERMISSIONS.md.

The deletes at the bottom are for the retention job, which runs as its own
DB user; the app's user has no DELETE on these tables.
"""

from datetime import datetime
from typing import Literal

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import UtcDateTime

KeyAction = Literal["key.created", "key.revoked", "key.deleted"]
ActorType = Literal["owner", "admin", "system"]

_utc = UtcDateTime()

_RECORD_KEY_EVENT = text(
    """
    INSERT INTO identity_api_key_audit_logs
        (user_id, action, actor_id, actor_type, target_type, target_id,
         request_id, source_ip, created_at)
    VALUES
        (:user_id, :action, :actor_id, :actor_type, 'api_key', :target_id,
         :request_id, :source_ip, :at)
    """
).bindparams(bindparam("at", type_=_utc))


async def record_key_event(
    session: AsyncSession,
    *,
    user_id: int,
    action: KeyAction,
    target_id: str,
    actor_id: int | None,
    actor_type: ActorType,
    source_ip: str | None,
    request_id: str | None,
    at: datetime,
) -> None:
    await session.execute(
        _RECORD_KEY_EVENT,
        {
            "user_id": user_id,
            "action": action,
            "actor_id": actor_id,
            "actor_type": actor_type,
            "target_id": target_id,
            "request_id": request_id,
            "source_ip": source_ip,
            "at": at,
        },
    )


_RECORD_AUTH_FAILURE = text(
    """
    INSERT INTO identity_auth_failure_logs
        (action, key_id, source_ip, reason, created_at)
    VALUES ('auth.failed', :key_id, :source_ip, :reason, :at)
    """
).bindparams(bindparam("at", type_=_utc))


async def record_auth_failure(
    session: AsyncSession, *, key_id: str, source_ip: str, reason: str, at: datetime
) -> None:
    await session.execute(
        _RECORD_AUTH_FAILURE,
        {"key_id": key_id, "source_ip": source_ip, "reason": reason, "at": at},
    )


# region Retention (run by app/jobs/retention.py, not by the app)
_DELETE_KEY_EVENTS_BEFORE = text(
    """
    DELETE FROM identity_api_key_audit_logs
    WHERE created_at < :before
    ORDER BY created_at
    LIMIT :batch
    """
).bindparams(bindparam("before", type_=_utc))


async def delete_key_events_before(
    session: AsyncSession, *, before: datetime, batch: int
) -> int:
    result = await session.execute(
        _DELETE_KEY_EVENTS_BEFORE, {"before": before, "batch": batch}
    )
    return result.rowcount


_DELETE_AUTH_FAILURES_BEFORE = text(
    """
    DELETE FROM identity_auth_failure_logs
    WHERE created_at < :before
    ORDER BY created_at
    LIMIT :batch
    """
).bindparams(bindparam("before", type_=_utc))


async def delete_auth_failures_before(
    session: AsyncSession, *, before: datetime, batch: int
) -> int:
    result = await session.execute(
        _DELETE_AUTH_FAILURES_BEFORE, {"before": before, "batch": batch}
    )
    return result.rowcount


# endregion
