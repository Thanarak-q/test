from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from app.services.api_key_auth import (
    DATABASE_TIMEOUT_SECONDS,
    NEGATIVE_CACHE_TTL_SECONDS,
    POSITIVE_CACHE_TTL_SECONDS,
    AuthInfrastructureError,
    validate_api_key,
)

KEY_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
SECRET = "Abcdef0123456789Abcdef0123456789"
TOKEN = f"mthw01_{KEY_ID}_{SECRET}"
KEY_HASH = "f6e9fb3ddc067872078fdf0d019bc10241c7c32261790ae6287425aaa25aa7f1"
NOW = datetime(2026, 9, 12, tzinfo=UTC)


class FakeCache:
    def __init__(self, negative=False, positive=None, error=None):
        self.negative = negative
        self.positive = positive
        self.error = error
        self.negative_writes = []
        self.positive_writes = []

    async def get_negative(self, key_id):
        if self.error:
            raise self.error
        return self.negative

    async def set_negative(self, key_id, ttl_seconds):
        if self.error:
            raise self.error
        self.negative_writes.append((key_id, ttl_seconds))

    async def get_positive(self, key_id):
        if self.error:
            raise self.error
        return self.positive

    async def set_positive(self, key_id, record, ttl_seconds):
        if self.error:
            raise self.error
        self.positive_writes.append((key_id, record, ttl_seconds))


class FakeDatabase:
    def __init__(self, record=None, error=None):
        self.record = record
        self.error = error
        self.queries = []
        self.last_used_updates = []

    async def get_by_key_id(self, key_id, *, timeout_seconds):
        if self.error:
            raise self.error
        self.queries.append((key_id, timeout_seconds))
        return self.record

    async def update_last_used(self, key_id, at):
        if self.error:
            raise self.error
        self.last_used_updates.append((key_id, at))


class FakeAudit:
    def __init__(self, error=None):
        self.error = error
        self.records = []

    async def record_failure(self, *, key_id, source_ip, reason):
        if self.error:
            raise self.error
        self.records.append((key_id, source_ip, reason))


def record(
    *,
    user_id=42,
    key_id=KEY_ID,
    key_hash=KEY_HASH,
    status="active",
    last_used_at=NOW,
):
    return {
        "key_id": key_id,
        "user_id": user_id,
        "key_hash": key_hash,
        "status": status,
        "last_used_at": last_used_at,
    }


def dependencies(*, cache=None, database=None, audit=None):
    return {
        "cache": cache or FakeCache(),
        "database": database or FakeDatabase(record=record()),
        "audit": audit or FakeAudit(),
        "now": lambda: NOW,
    }


@pytest.mark.parametrize(
    "token",
    [
        "wrong_" + KEY_ID + "_" + SECRET,
        f"mthw01_{KEY_ID}_{SECRET}_extra",
        f"mthw01_01ARZ3NDEKTSV4RRFFQ69G5FAI_{SECRET}",
        f"mthw01_{KEY_ID}_short",
    ],
)
async def test_malformed_token_rejects_without_io(token):
    cache = FakeCache()
    database = FakeDatabase()

    with pytest.raises(HTTPException) as exc_info:
        await validate_api_key(
            token,
            "203.0.113.8",
            **dependencies(cache=cache, database=database),
        )

    assert exc_info.value.status_code == 401
    assert cache.negative_writes == []
    assert database.queries == []


async def test_negative_cache_rejects_without_database_query():
    cache = FakeCache(negative=True)
    database = FakeDatabase()
    audit = FakeAudit()

    with pytest.raises(HTTPException) as exc_info:
        await validate_api_key(
            TOKEN,
            "203.0.113.8",
            **dependencies(cache=cache, database=database, audit=audit),
        )

    assert exc_info.value.status_code == 401
    assert database.queries == []
    assert audit.records == [(KEY_ID, "203.0.113.8", "key_not_found")]


async def test_positive_cache_hit_returns_record_identity():
    cached = record(last_used_at=NOW)
    cache = FakeCache(positive=cached)
    database = FakeDatabase()

    result = await validate_api_key(
        TOKEN, "203.0.113.8", **dependencies(cache=cache, database=database)
    )

    assert result == {"user_id": 42, "key_id": KEY_ID}
    assert database.queries == []
    assert database.last_used_updates == []


@pytest.mark.parametrize(
    "cached",
    [
        {"key_id": KEY_ID, "user_id": 42},
        {**record(), "user_id": "42"},
    ],
)
async def test_invalid_positive_cache_is_a_database_miss(cached):
    database = FakeDatabase(record=record(user_id=77))

    result = await validate_api_key(
        TOKEN,
        "203.0.113.8",
        **dependencies(cache=FakeCache(positive=cached), database=database),
    )

    assert result["user_id"] == 77
    assert database.queries == [(KEY_ID, DATABASE_TIMEOUT_SECONDS)]


async def test_revoked_positive_cache_is_a_401_without_database_fallback():
    cache = FakeCache(positive=record(status="revoked"))
    database = FakeDatabase(record=record(user_id=77))

    with pytest.raises(HTTPException) as exc_info:
        await validate_api_key(
            TOKEN,
            "203.0.113.8",
            **dependencies(cache=cache, database=database),
        )

    assert exc_info.value.status_code == 401
    assert database.queries == []


async def test_database_miss_writes_negative_cache():
    cache = FakeCache()
    database = FakeDatabase(record=None)
    audit = FakeAudit()

    with pytest.raises(HTTPException) as exc_info:
        await validate_api_key(
            TOKEN,
            "203.0.113.8",
            **dependencies(cache=cache, database=database, audit=audit),
        )

    assert exc_info.value.status_code == 401
    assert cache.negative_writes == [(KEY_ID, NEGATIVE_CACHE_TTL_SECONDS)]
    assert audit.records[-1][-1] == "key_not_found"


@pytest.mark.parametrize("field", ["key_hash", "status"])
async def test_invalid_database_credentials_have_same_401_contract(field):
    values = record()
    values[field] = "f" * 64 if field == "key_hash" else "revoked"
    audit = FakeAudit()

    with pytest.raises(HTTPException) as exc_info:
        await validate_api_key(
            TOKEN,
            "203.0.113.8",
            **dependencies(database=FakeDatabase(record=values), audit=audit),
        )

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid API key."


@pytest.mark.parametrize("dependency", ["cache", "database"])
async def test_infrastructure_failures_are_503_without_fallback(dependency):
    failing = AuthInfrastructureError("dependency failure")
    cache = FakeCache(error=failing) if dependency == "cache" else FakeCache()
    database = (
        FakeDatabase(error=failing) if dependency == "database" else FakeDatabase()
    )

    with pytest.raises(HTTPException) as exc_info:
        await validate_api_key(
            TOKEN,
            "203.0.113.8",
            **dependencies(cache=cache, database=database),
        )

    assert exc_info.value.status_code == 503
    if dependency == "database":
        assert database.queries == []


async def test_positive_cache_ttl_and_last_used_throttle():
    old = NOW - timedelta(minutes=6)
    cache = FakeCache(positive=record(last_used_at=old))
    database = FakeDatabase()

    await validate_api_key(
        TOKEN,
        "203.0.113.8",
        **dependencies(cache=cache, database=database),
    )

    assert database.last_used_updates == [(KEY_ID, NOW)]
    assert cache.positive_writes[0][2] == POSITIVE_CACHE_TTL_SECONDS


async def test_audit_failure_does_not_change_credential_401():
    audit = FakeAudit(error=AuthInfrastructureError("audit unavailable"))
    database = FakeDatabase(record=None)

    with pytest.raises(HTTPException) as exc_info:
        await validate_api_key(
            TOKEN,
            "203.0.113.8",
            **dependencies(database=database, audit=audit),
        )

    assert exc_info.value.status_code == 401


async def test_secret_is_not_in_result_or_audit():
    audit = FakeAudit()
    database = FakeDatabase(record=record(key_hash="f" * 64))

    with pytest.raises(HTTPException):
        await validate_api_key(
            TOKEN,
            "203.0.113.8",
            **dependencies(database=database, audit=audit),
        )

    assert SECRET not in repr(audit.records)
