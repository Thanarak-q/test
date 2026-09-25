"""API key management for the dashboard: create, list, revoke, delete.

Every function takes the user_id of the verified session. Ownership is
enforced in each query (app/repos/api_keys.py), and a key that is not yours
gets exactly the same 404 as a key that does not exist.
"""

import asyncio
import hashlib
import logging
import os
import secrets
import string
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.api_keys import (
    CACHE_INVALIDATION_ATTEMPTS,
    CACHE_INVALIDATION_BACKOFF_SECONDS,
    KEY_TOKEN_PREFIX,
    MAX_ACTIVE_KEYS,
    SECRET_LENGTH,
)
from app.envelope import AppError
from app.repos import api_key_repo, audit_repo
from app.repos.auth_cache import RedisAuthCache
from app.services.validate_api_key import AuthInfrastructureError

logger = logging.getLogger(__name__)

_BASE62 = string.ascii_letters + string.digits
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


@dataclass(frozen=True)
class CreatedKey:
    id: str
    name: str
    key: str  # the only time the full key exists outside the caller's hands
    key_prefix: str
    created_at: datetime


@dataclass(frozen=True)
class KeySummary:
    id: str
    name: str
    key_prefix: str
    status: str
    created_at: datetime
    last_used_at: datetime | None
    never_used: bool


@dataclass(frozen=True)
class RequestContext:
    """Who did it and from where, for the audit row."""

    user_id: int
    source_ip: str | None
    request_id: str | None = None


def key_prefix(key_id: str) -> str:
    """The display prefix. Built here only; it contains nothing of the secret."""
    return f"{KEY_TOKEN_PREFIX}_{key_id}"


async def create_key(
    session: AsyncSession, ctx: RequestContext, name: str
) -> CreatedKey:
    key_id = _new_ulid()
    # secret stays a local: it is never attached to an ORM object, logged,
    # cached, or stored. Only its hash leaves this function besides the
    # one-time response.
    secret = "".join(secrets.choice(_BASE62) for _ in range(SECRET_LENGTH))
    # SHA-256, not bcrypt/argon2: the secret is ~190 bits from a CSPRNG, not a
    # password. Slow hashing compensates for low entropy, which this does not
    # have, and the hash is recomputed on every authenticated request.
    key_hash = hashlib.sha256(secret.encode("ascii")).hexdigest()
    now = datetime.now(UTC)

    async with session.begin():
        await api_key_repo.lock_user(session, user_id=ctx.user_id)
        inserted = await api_key_repo.insert_if_under_limit(
            session,
            key_id=key_id,
            user_id=ctx.user_id,
            name=name,
            key_hash=key_hash,
            created_at=now,
            max_active=MAX_ACTIVE_KEYS,
        )
        if not inserted:
            raise AppError(
                "identity_api_key_limit_reached",
                f"You can have up to {MAX_ACTIVE_KEYS} active API keys. "
                "Revoke one before creating another.",
                409,
            )
        await _audit(session, ctx, "key.created", key_id, now)

    return CreatedKey(
        id=key_id,
        name=name,
        key=f"{KEY_TOKEN_PREFIX}_{key_id}_{secret}",
        key_prefix=key_prefix(key_id),
        created_at=now,
    )


async def list_keys(session: AsyncSession, user_id: int) -> list[KeySummary]:
    async with session.begin():
        rows = await api_key_repo.list_for_user(session, user_id=user_id)
    return [
        KeySummary(
            id=row.id,
            name=row.name,
            key_prefix=key_prefix(row.id),
            status=row.status,
            created_at=row.created_at,
            last_used_at=row.last_used_at,
            never_used=row.last_used_at is None,
        )
        for row in rows
    ]


async def labels(
    session: AsyncSession, user_id: int, key_ids: list[str]
) -> dict[str, api_key_repo.KeyLabelRow]:
    """For other modules: runs inside the caller's transaction."""
    rows = await api_key_repo.labels_for_user(session, user_id=user_id, key_ids=key_ids)
    return {row.id: row for row in rows}


async def revoke_key(
    session: AsyncSession, redis: Redis, ctx: RequestContext, key_id: str
) -> None:
    now = datetime.now(UTC)
    async with session.begin():
        if await api_key_repo.revoke(
            session, key_id=key_id, user_id=ctx.user_id, at=now
        ):
            await _audit(session, ctx, "key.revoked", key_id, now)
        else:
            status = await api_key_repo.get_status(
                session, key_id=key_id, user_id=ctx.user_id
            )
            if status is None or status == "deleted":
                raise _not_found()
            # already revoked: idempotent, nothing changed, nothing audited

    # After the commit, so a concurrent lookup cannot re-cache the old status.
    # Also on the idempotent path: a retry after a failed invalidation must
    # get another chance to clear the cache.
    await _invalidate_cache(RedisAuthCache(redis), key_id)


async def delete_key(
    session: AsyncSession, redis: Redis, ctx: RequestContext, key_id: str
) -> None:
    now = datetime.now(UTC)
    async with session.begin():
        if await api_key_repo.soft_delete(
            session, key_id=key_id, user_id=ctx.user_id, at=now
        ):
            await _audit(session, ctx, "key.deleted", key_id, now)
        elif (
            await api_key_repo.get_status(session, key_id=key_id, user_id=ctx.user_id)
            != "deleted"
        ):
            raise _not_found()

    await _invalidate_cache(RedisAuthCache(redis), key_id)


async def _audit(
    session: AsyncSession,
    ctx: RequestContext,
    action: audit_repo.KeyAction,
    key_id: str,
    at: datetime,
) -> None:
    # Same transaction as the change: if this insert fails, the change does too.
    await audit_repo.record_key_event(
        session,
        user_id=ctx.user_id,
        action=action,
        target_id=key_id,
        actor_id=ctx.user_id,
        actor_type="owner",
        source_ip=ctx.source_ip,
        request_id=ctx.request_id,
        at=at,
    )


async def _invalidate_cache(cache: RedisAuthCache, key_id: str) -> None:
    """DEL auth:{key_id}, retried; never report success if it did not happen.

    If every attempt fails the key is revoked in MySQL but may still be served
    from the positive cache for up to its TTL (60s) — the documented
    worst-case window. The caller gets a 500 and must retry.
    """
    for attempt in range(1, CACHE_INVALIDATION_ATTEMPTS + 1):
        try:
            await cache.invalidate(key_id)
            return
        except AuthInfrastructureError:
            if attempt < CACHE_INVALIDATION_ATTEMPTS:
                await asyncio.sleep(CACHE_INVALIDATION_BACKOFF_SECONDS * attempt)

    logger.error(
        "ALERT api key cache invalidation failed; key may authenticate for up "
        "to the positive cache TTL",
        extra={"key_id": key_id},
    )
    raise AppError(
        "identity_api_key_revocation_pending",
        "The key is not revoked yet. Try again.",
        500,
    )


def _not_found() -> AppError:
    # One error for "does not exist" and "belongs to someone else".
    return AppError("identity_api_key_not_found", "API key not found.", 404)


def _new_ulid() -> str:
    """48-bit millisecond timestamp + 80 random bits, Crockford base32."""
    value = (time.time_ns() // 1_000_000) << 80 | int.from_bytes(os.urandom(10))
    return "".join(_CROCKFORD[(value >> shift) & 31] for shift in range(125, -1, -5))
