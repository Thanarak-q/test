"""Standalone API key validation flow with injectable infrastructure ports."""

import hashlib
import hmac
import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Protocol, TypedDict

from fastapi import HTTPException

logger = logging.getLogger(__name__)

NEGATIVE_CACHE_TTL_SECONDS = 30
POSITIVE_CACHE_TTL_SECONDS = 60
LAST_USED_THROTTLE = timedelta(minutes=5)
DATABASE_TIMEOUT_SECONDS = 2.0
INVALID_API_KEY_MESSAGE = "Invalid API key."
AUTH_UNAVAILABLE_MESSAGE = "Authentication is temporarily unavailable."

_TOKEN_PREFIX = "mthw01"
_ULID_RE = re.compile(r"[0-7][0-9A-HJKMNP-TV-Z]{25}\Z")
_BASE62_RE = re.compile(r"[A-Za-z0-9]{32}\Z")
_SHA256_RE = re.compile(r"[0-9a-fA-F]{64}\Z")
_POSITIVE_CACHE_FIELDS = {"key_id", "user_id", "key_hash", "status", "last_used_at"}


class AuthInfrastructureError(RuntimeError):
    """An auth dependency failed and must be exposed as HTTP 503."""


class AuthIdentity(TypedDict):
    user_id: int
    key_id: str


class AuthCache(Protocol):
    async def get_negative(self, key_id: str) -> bool | None: ...

    async def set_negative(self, key_id: str, ttl_seconds: int) -> None: ...

    async def get_positive(self, key_id: str) -> Mapping[str, object] | None: ...

    async def set_positive(
        self,
        key_id: str,
        record: Mapping[str, object],
        ttl_seconds: int,
    ) -> None: ...


class AuthDatabase(Protocol):
    async def get_by_key_id(
        self, key_id: str, *, timeout_seconds: float
    ) -> Mapping[str, object] | None: ...

    async def update_last_used(self, key_id: str, at: datetime) -> None: ...


class AuthFailureAudit(Protocol):
    async def record_failure(
        self, *, key_id: str, source_ip: str, reason: str
    ) -> None: ...


@dataclass(frozen=True)
class _ValidatedRecord:
    key_id: str
    user_id: int
    key_hash: str
    status: str
    last_used_at: datetime | None

    def as_cache_record(self) -> dict[str, object]:
        return {
            "key_id": self.key_id,
            "user_id": self.user_id,
            "key_hash": self.key_hash,
            "status": self.status,
            "last_used_at": self.last_used_at,
        }


def negative_cache_key(key_id: str) -> str:
    return f"auth:neg:{key_id}"


def positive_cache_key(key_id: str) -> str:
    return f"auth:{key_id}"


async def validate_api_key(
    token: str,
    source_ip: str,
    *,
    cache: AuthCache,
    database: AuthDatabase,
    audit: AuthFailureAudit,
    now: Callable[[], datetime] | None = None,
) -> AuthIdentity:
    """Validate a token without reading request headers or constructing identity.

    The caller is responsible for refunding the pre-auth IP rate limit token
    once this returns successfully, so that bucket counts only failures.
    """
    parsed = _parse_token(token)
    if parsed is None:
        raise _invalid_credential()

    key_id, secret = parsed
    try:
        if await cache.get_negative(key_id):
            await _audit_failure(audit, key_id, source_ip, "key_not_found")
            raise _invalid_credential()

        key_hash = hashlib.sha256(secret.encode("ascii")).hexdigest()
        cached = await cache.get_positive(key_id)
        record = _validate_record(cached, key_id) if cached is not None else None
        from_cache = record is not None

        if record is None:
            database_record = await database.get_by_key_id(
                key_id, timeout_seconds=DATABASE_TIMEOUT_SECONDS
            )
            if database_record is None:
                await cache.set_negative(key_id, NEGATIVE_CACHE_TTL_SECONDS)
                await _audit_failure(audit, key_id, source_ip, "key_not_found")
                raise _invalid_credential()

            record = _validate_record(database_record, key_id)
            if record is None:
                await _audit_failure(audit, key_id, source_ip, "invalid_credential")
                raise _invalid_credential()

        # Both checks are evaluated before branching so that a revoked key and
        # a wrong secret take the same path. Short-circuiting on status would
        # skip the comparison and make the two distinguishable by timing.
        hash_matches = hmac.compare_digest(record.key_hash, key_hash)
        if record.status != "active" or not hash_matches:
            await _audit_failure(audit, key_id, source_ip, "invalid_credential")
            raise _invalid_credential()

        previous_last_used = record.last_used_at
        record = await _refresh_last_used(record, key_id, database, now)

        # Write the cache on a miss, or when last_used_at moved, so the
        # throttle window is measured from the stored value rather than
        # restarting every time the entry expires.
        if not from_cache or record.last_used_at != previous_last_used:
            await cache.set_positive(
                key_id,
                record.as_cache_record(),
                POSITIVE_CACHE_TTL_SECONDS,
            )
        return {"user_id": record.user_id, "key_id": record.key_id}
    except AuthInfrastructureError as exc:
        raise _auth_unavailable() from exc


def _parse_token(token: str) -> tuple[str, str] | None:
    parts = token.split("_")
    if len(parts) != 3 or parts[0] != _TOKEN_PREFIX:
        return None

    key_id, secret = parts[1].upper(), parts[2]
    if not _ULID_RE.fullmatch(key_id) or not _BASE62_RE.fullmatch(secret):
        return None
    return key_id, secret


def _validate_record(
    raw: Mapping[str, object] | None, expected_key_id: str
) -> _ValidatedRecord | None:
    if raw is None or set(raw) != _POSITIVE_CACHE_FIELDS:
        return None

    key_id = raw["key_id"]
    user_id = raw["user_id"]
    key_hash = raw["key_hash"]
    status = raw["status"]
    last_used_at = raw["last_used_at"]
    if (
        not isinstance(key_id, str)
        or key_id != expected_key_id
        or not isinstance(user_id, int)
        or isinstance(user_id, bool)
        or user_id < 1
        or not isinstance(key_hash, str)
        or not _SHA256_RE.fullmatch(key_hash)
        or not isinstance(status, str)
        or not isinstance(last_used_at, datetime | type(None))
        or (last_used_at is not None and last_used_at.tzinfo is None)
    ):
        return None

    return _ValidatedRecord(
        key_id=key_id,
        user_id=user_id,
        key_hash=key_hash.lower(),
        status=status,
        last_used_at=last_used_at,
    )


async def _refresh_last_used(
    record: _ValidatedRecord,
    key_id: str,
    database: AuthDatabase,
    now_factory: Callable[[], datetime] | None,
) -> _ValidatedRecord:
    current_time = (now_factory or _utc_now)()
    if (
        record.last_used_at is not None
        and current_time - record.last_used_at < LAST_USED_THROTTLE
    ):
        return record

    await database.update_last_used(key_id, current_time)
    return replace(record, last_used_at=current_time)


async def _audit_failure(
    audit: AuthFailureAudit, key_id: str, source_ip: str, reason: str
) -> None:
    """Record a failed attempt without letting the audit path reject the request.

    A failure here is logged rather than swallowed silently: if auditing stops
    working, the repudiation control it exists for is gone and someone needs
    to know.
    """
    try:
        await audit.record_failure(key_id=key_id, source_ip=source_ip, reason=reason)
    except AuthInfrastructureError:
        logger.warning("auth failure audit unavailable", extra={"key_id": key_id})


def _invalid_credential() -> HTTPException:
    return HTTPException(status_code=401, detail=INVALID_API_KEY_MESSAGE)


def _auth_unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail=AUTH_UNAVAILABLE_MESSAGE)


def _utc_now() -> datetime:
    return datetime.now(UTC)
