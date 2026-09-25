"""Append-only audit tables. INSERT only — see docs/DB_PERMISSIONS.md."""

from datetime import datetime
from typing import Literal

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ApiKeyAuditLog, AuthFailureLog

KeyAction = Literal["key.created", "key.revoked", "key.deleted"]
ActorType = Literal["owner", "admin", "system"]


async def insert_key_event(
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
        insert(ApiKeyAuditLog).values(
            user_id=user_id,
            action=action,
            actor_id=actor_id,
            actor_type=actor_type,
            target_type="api_key",
            target_id=target_id,
            request_id=request_id,
            source_ip=source_ip,
            created_at=at,
        )
    )


async def insert_auth_failure(
    session: AsyncSession,
    *,
    key_id: str,
    source_ip: str,
    reason: str,
    at: datetime,
) -> None:
    await session.execute(
        insert(AuthFailureLog).values(
            action="auth.failed",
            key_id=key_id,
            source_ip=source_ip,
            reason=reason,
            created_at=at,
        )
    )
