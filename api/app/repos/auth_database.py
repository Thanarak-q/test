"""MySQL side of API key authentication, for validate_api_key.

Both adapters open their own short sessions instead of borrowing the
request's:
- the lookup releases its connection as soon as it has the record, so an
  API request never holds a pooled connection past authentication
  (docs/NON_FUNCTIONAL.md §2.2);
- the failure audit must land even though a failed authentication raises
  401 and rolls back the request's transaction.
They are the one place in app/repos/ that opens a transaction; the repo
functions they call still never commit.
"""

import asyncio
from collections.abc import Mapping
from dataclasses import asdict
from datetime import UTC, datetime

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.repos import api_key_repo, audit_repo
from app.services.validate_api_key import AuthInfrastructureError

_INFRA_ERRORS = (SQLAlchemyError, OSError, TimeoutError)


class SqlAuthDatabase:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get_by_key_id(
        self, key_id: str, *, timeout_seconds: float
    ) -> Mapping[str, object] | None:
        try:
            async with self._session_factory() as session:
                row = await asyncio.wait_for(
                    api_key_repo.get_for_auth(session, key_id=key_id),
                    timeout=timeout_seconds,
                )
        except _INFRA_ERRORS as exc:
            raise AuthInfrastructureError("auth database unavailable") from exc
        return asdict(row) if row else None

    async def update_last_used(
        self, key_id: str, *, user_id: int, at: datetime
    ) -> None:
        try:
            async with self._session_factory.begin() as session:
                await api_key_repo.touch_last_used(
                    session, key_id=key_id, user_id=user_id, at=at
                )
        except _INFRA_ERRORS as exc:
            raise AuthInfrastructureError("auth database unavailable") from exc


class SqlFailureAudit:
    """Writes auth.failed in its own short transaction (see module docstring)."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def record_failure(self, *, key_id: str, source_ip: str, reason: str) -> None:
        try:
            async with self._session_factory.begin() as session:
                await audit_repo.record_auth_failure(
                    session,
                    key_id=key_id,
                    source_ip=source_ip,
                    reason=reason,
                    at=datetime.now(UTC),
                )
        except _INFRA_ERRORS as exc:
            raise AuthInfrastructureError("auth audit unavailable") from exc
