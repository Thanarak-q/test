"""docs/NON_FUNCTIONAL.md §3: dependency failures are 503, and a cached key
keeps validating while MySQL is down."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import ApiKeyAuditLog
from app.repos import api_key_repo
from app.repos.auth_cache import RedisAuthCache
from app.repos.auth_database import SqlAuthDatabase, SqlFailureAudit
from app.services.validate_api_key import validate_api_key
from tests.repos.helpers import ALICE, as_user, seed_key


@pytest.mark.parametrize(
    "error",
    [
        OperationalError("SELECT 1", {}, Exception("gone away")),
        PoolTimeoutError("pool exhausted"),
    ],
)
async def test_database_outage_on_a_dashboard_route_is_503(client, monkeypatch, error):
    async def broken(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(api_key_repo, "list_for_user", broken)

    response = await client.post("/v1/api-keys/list", headers=as_user(ALICE))

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"


async def test_cached_key_validates_while_the_database_is_down(db, redis):
    key_id, token = await seed_key(db, user_id=ALICE)
    # Warm the cache, with a last_used_at old enough to trigger a write.
    await validate_api_key(
        token,
        "203.0.113.9",
        cache=RedisAuthCache(redis),
        database=SqlAuthDatabase(db),
        audit=SqlFailureAudit(db),
        now=lambda: datetime.now(UTC) - timedelta(minutes=10),
    )

    dead = create_async_engine(
        "mysql+aiomysql://root:x@127.0.0.1:1/none", connect_args={"connect_timeout": 1}
    )
    try:
        identity = await validate_api_key(
            token,
            "203.0.113.9",
            cache=RedisAuthCache(redis),
            database=SqlAuthDatabase(async_sessionmaker(dead)),
            audit=SqlFailureAudit(async_sessionmaker(dead)),
        )
    finally:
        await dead.dispose()

    assert identity == {"user_id": ALICE, "key_id": key_id}


async def test_every_response_carries_a_request_id_that_audit_rows_keep(client, db):
    response = await client.post(
        "/v1/api-keys/create", json={"name": "traced"}, headers=as_user(ALICE)
    )

    request_id = response.headers["X-Request-Id"]
    async with db() as session:
        audited = await session.scalar(select(ApiKeyAuditLog.request_id))
    assert len(request_id) == 32 and audited == request_id


async def test_request_id_is_kept_from_the_proxy_only(client):
    from_proxy = await client.post(
        "/v1/api-keys/list",
        headers={**as_user(ALICE), "X-Request-Id": "nginx-abc123"},
    )

    assert from_proxy.headers["X-Request-Id"] == "nginx-abc123"


async def test_request_id_from_an_untrusted_peer_is_replaced(client):
    from app.main import app

    app.state.trusted_proxies = frozenset({"10.9.9.9"})
    response = await client.post(
        "/v1/api-keys/list",
        headers={**as_user(ALICE), "X-Request-Id": "attacker-chosen"},
    )

    assert response.headers["X-Request-Id"] != "attacker-chosen"
