"""Redis side of API key authentication.

Every Redis failure becomes AuthInfrastructureError, which validate_api_key
turns into a 503. Never catch RedisError here and return None: None means
"not cached", the caller would fall through to MySQL, and Redis being down
would silently become a database flood — fail-open for the whole system.
"""

import json
from collections.abc import Mapping
from datetime import datetime

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.services.validate_api_key import (
    AuthInfrastructureError,
    negative_cache_key,
    positive_cache_key,
)


class RedisAuthCache:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def get_negative(self, key_id: str) -> bool:
        try:
            return await self._redis.exists(negative_cache_key(key_id)) == 1
        except RedisError as exc:
            raise AuthInfrastructureError("auth cache unavailable") from exc

    async def set_negative(self, key_id: str, ttl_seconds: int) -> None:
        try:
            await self._redis.set(negative_cache_key(key_id), "1", ex=ttl_seconds)
        except RedisError as exc:
            raise AuthInfrastructureError("auth cache unavailable") from exc

    async def get_positive(self, key_id: str) -> Mapping[str, object] | None:
        try:
            raw = await self._redis.get(positive_cache_key(key_id))
        except RedisError as exc:
            raise AuthInfrastructureError("auth cache unavailable") from exc
        if raw is None:
            return None
        # A corrupt entry is a cache miss, not an outage: the caller re-reads
        # MySQL for this one key and overwrites the entry.
        return _decode(raw)

    async def set_positive(
        self, key_id: str, record: Mapping[str, object], ttl_seconds: int
    ) -> None:
        try:
            await self._redis.set(
                positive_cache_key(key_id), _encode(record), ex=ttl_seconds
            )
        except RedisError as exc:
            raise AuthInfrastructureError("auth cache unavailable") from exc

    async def invalidate(self, key_id: str) -> None:
        try:
            await self._redis.delete(positive_cache_key(key_id))
        except RedisError as exc:
            raise AuthInfrastructureError("auth cache unavailable") from exc


def _encode(record: Mapping[str, object]) -> str:
    last_used_at = record.get("last_used_at")
    return json.dumps(
        {
            **record,
            # ISO-8601 with offset, so it parses back to an aware datetime.
            "last_used_at": (
                last_used_at.isoformat() if isinstance(last_used_at, datetime) else None
            ),
        }
    )


def _decode(raw: str | bytes) -> dict[str, object] | None:
    try:
        record = json.loads(raw)
        if not isinstance(record, dict):
            return None
        last_used_at = record.get("last_used_at")
        if last_used_at is not None:
            # A value without an offset stays naive here, and _validate_record
            # rejects it — that is the intended outcome.
            record["last_used_at"] = datetime.fromisoformat(last_used_at)
        return record
    except (ValueError, TypeError):
        return None
