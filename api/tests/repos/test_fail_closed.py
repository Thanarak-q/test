"""Fail-closed, proven against real Redis and MySQL rather than fakes."""

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import ApiKey, AuthFailureLog
from app.repos import api_keys
from app.repos.auth_cache import RedisAuthCache
from app.repos.auth_database import SqlAuthDatabase, SqlFailureAudit
from app.services.validate_api_key import (
    AuthInfrastructureError,
    positive_cache_key,
    validate_api_key,
)
from tests.repos.helpers import new_token, seed_key


class SpyDatabase:
    """Wraps the real SqlAuthDatabase and counts calls into it."""

    def __init__(self, inner):
        self.inner = inner
        self.calls = 0

    async def get_by_key_id(self, key_id, *, timeout_seconds):
        self.calls += 1
        return await self.inner.get_by_key_id(key_id, timeout_seconds=timeout_seconds)

    async def update_last_used(self, key_id, *, user_id, at):
        self.calls += 1
        await self.inner.update_last_used(key_id, user_id=user_id, at=at)


async def _validate(token, *, cache, database, factory):
    return await validate_api_key(
        token,
        "203.0.113.9",
        cache=cache,
        database=database,
        audit=SqlFailureAudit(factory),
    )


# region Redis down


async def test_redis_down_is_503_and_never_reaches_the_database(db, unreachable_redis):
    key_id, token = await seed_key(db, user_id=1)
    async with db() as session:
        database = SpyDatabase(SqlAuthDatabase(session))

        with pytest.raises(HTTPException) as exc_info:
            await _validate(
                token,
                cache=RedisAuthCache(unreachable_redis),
                database=database,
                factory=db,
            )

    assert exc_info.value.status_code == 503
    assert database.calls == 0  # no fallback to MySQL on every request


@pytest.mark.parametrize(
    "call",
    [
        lambda cache: cache.get_negative("K"),
        lambda cache: cache.set_negative("K", 30),
        lambda cache: cache.get_positive("K"),
        lambda cache: cache.set_positive("K", {"last_used_at": None}, 60),
        lambda cache: cache.invalidate("K"),
    ],
)
async def test_every_cache_operation_raises_rather_than_returning(
    unreachable_redis, call
):
    with pytest.raises(AuthInfrastructureError):
        await call(RedisAuthCache(unreachable_redis))


# endregion

# region MySQL down


async def test_database_down_is_503_not_401(redis):
    engine = create_async_engine(
        "mysql+aiomysql://root:x@127.0.0.1:1/none", connect_args={"connect_timeout": 1}
    )
    factory = async_sessionmaker(engine)
    _, _, token = new_token()
    try:
        async with factory() as session:
            with pytest.raises(HTTPException) as exc_info:
                await _validate(
                    token,
                    cache=RedisAuthCache(redis),
                    database=SqlAuthDatabase(session),
                    factory=factory,
                )
    finally:
        await engine.dispose()

    assert exc_info.value.status_code == 503


async def test_database_timeout_is_enforced(db, monkeypatch):
    async def slow(*_args, **_kwargs):
        await asyncio.sleep(5)

    monkeypatch.setattr(api_keys, "get_auth_record", slow)
    async with db() as session:
        started = asyncio.get_running_loop().time()
        with pytest.raises(AuthInfrastructureError):
            await SqlAuthDatabase(session).get_by_key_id("K", timeout_seconds=0.2)

    assert asyncio.get_running_loop().time() - started < 1


async def test_failure_audit_raises_when_database_is_down():
    engine = create_async_engine(
        "mysql+aiomysql://root:x@127.0.0.1:1/none", connect_args={"connect_timeout": 1}
    )
    try:
        with pytest.raises(AuthInfrastructureError):
            await SqlFailureAudit(async_sessionmaker(engine)).record_failure(
                key_id="K", source_ip="203.0.113.9", reason="key_not_found"
            )
    finally:
        await engine.dispose()


# endregion

# region Working path


async def test_valid_key_authenticates_then_serves_from_cache(db, redis):
    key_id, token = await seed_key(db, user_id=7)

    async with db.begin() as session:
        first = SpyDatabase(SqlAuthDatabase(session))
        identity = await _validate(
            token, cache=RedisAuthCache(redis), database=first, factory=db
        )
    async with db.begin() as session:
        second = SpyDatabase(SqlAuthDatabase(session))
        again = await _validate(
            token, cache=RedisAuthCache(redis), database=second, factory=db
        )

    assert identity == {"user_id": 7, "key_id": key_id}
    assert again == identity
    assert first.calls == 2  # lookup + last_used_at
    assert second.calls == 0  # cache hit, last_used_at inside the throttle


async def test_cache_round_trips_an_aware_last_used_at(redis):
    cache = RedisAuthCache(redis)
    at = datetime(2026, 9, 25, 4, 0, tzinfo=UTC) + timedelta(microseconds=123)
    await cache.set_positive(
        "K",
        {
            "key_id": "K",
            "user_id": 1,
            "key_hash": "a" * 64,
            "status": "active",
            "last_used_at": at,
        },
        60,
    )

    record = await cache.get_positive("K")

    assert record["last_used_at"] == at
    assert record["last_used_at"].tzinfo is not None
    assert await redis.ttl(positive_cache_key("K")) > 0


async def test_naive_cached_timestamp_is_treated_as_a_miss(db, redis):
    key_id, token = await seed_key(db, user_id=7)
    poisoned = {
        "key_id": key_id,
        "user_id": 99,
        "key_hash": "0" * 64,
        "status": "active",
        "last_used_at": "2026-09-25T04:00:00",  # no offset
    }
    await redis.set(positive_cache_key(key_id), json.dumps(poisoned))

    async with db.begin() as session:
        database = SpyDatabase(SqlAuthDatabase(session))
        identity = await _validate(
            token, cache=RedisAuthCache(redis), database=database, factory=db
        )

    assert identity["user_id"] == 7  # from MySQL, not the poisoned entry
    assert database.calls >= 1


async def test_unknown_key_is_401_and_audited(db, redis):
    key_id, _, token = new_token()

    async with db() as session:
        with pytest.raises(HTTPException) as exc_info:
            await _validate(
                token,
                cache=RedisAuthCache(redis),
                database=SqlAuthDatabase(session),
                factory=db,
            )

    assert exc_info.value.status_code == 401
    async with db() as session:
        failure = (await session.execute(select(AuthFailureLog))).scalar_one()
    assert (failure.key_id, failure.reason) == (key_id, "key_not_found")


async def test_status_not_revoked_at_decides_validity(db, redis):
    key_id, token = await seed_key(db, user_id=7)
    async with db.begin() as session:
        await session.execute(
            update(ApiKey)
            .where(ApiKey.id == key_id)
            .values(revoked_at=datetime.now(UTC))
        )

    async with db.begin() as session:
        identity = await _validate(
            token,
            cache=RedisAuthCache(redis),
            database=SqlAuthDatabase(session),
            factory=db,
        )

    assert identity["key_id"] == key_id


# endregion
