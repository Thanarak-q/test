"""MySQL side of API key authentication, for validate_api_key."""

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.repos import api_key_audit, api_keys
from app.services.validate_api_key import AuthInfrastructureError

_INFRA_ERRORS = (SQLAlchemyError, OSError, TimeoutError)


class SqlAuthDatabase:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_key_id(
        self, key_id: str, *, timeout_seconds: float
    ) -> Mapping[str, object] | None:
        try:
            return await asyncio.wait_for(
                api_keys.get_auth_record(self._session, key_id),
                timeout=timeout_seconds,
            )
        except _INFRA_ERRORS as exc:
            # A query cancelled mid-flight leaves the connection in an unknown
            # state; drop it rather than hand it back to the pool.
            await _invalidate_quietly(self._session)
            raise AuthInfrastructureError("auth database unavailable") from exc

    async def update_last_used(
        self, key_id: str, *, user_id: int, at: datetime
    ) -> None:
        try:
            await api_keys.touch_last_used(
                self._session, key_id=key_id, user_id=user_id, at=at
            )
        except _INFRA_ERRORS as exc:
            raise AuthInfrastructureError("auth database unavailable") from exc


class SqlFailureAudit:
    """Writes auth.failed in its own short transaction.

    The one repo adapter that commits, and it has to: a failed authentication
    raises 401, which rolls back the request's transaction, so a row written
    there would never land.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def record_failure(self, *, key_id: str, source_ip: str, reason: str) -> None:
        try:
            async with self._session_factory.begin() as session:
                await api_key_audit.insert_auth_failure(
                    session,
                    key_id=key_id,
                    source_ip=source_ip,
                    reason=reason,
                    at=datetime.now(UTC),
                )
        except _INFRA_ERRORS as exc:
            raise AuthInfrastructureError("auth audit unavailable") from exc


async def _invalidate_quietly(session: AsyncSession) -> None:
    try:
        await session.invalidate()
    except Exception:  # noqa: BLE001 — already failing; the original error wins
        pass
