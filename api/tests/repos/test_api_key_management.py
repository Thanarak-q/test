"""Key management over HTTP, against real MySQL and Redis.

The ownership tests are the point of this file: they prove another user's key
is unreachable through every route, and that the refusal gives nothing away.
"""

import asyncio
import hashlib

import pytest
from sqlalchemy import func, select

from app.constants.api_keys import MAX_ACTIVE_KEYS as MAX_KEYS
from app.main import app
from app.models import ApiKey, ApiKeyAuditLog
from app.repos.auth_cache import RedisAuthCache
from app.repos.auth_database import SqlAuthDatabase, SqlFailureAudit
from app.services.mgmt_rate_limit import bucket_key
from app.services.validate_api_key import positive_cache_key, validate_api_key
from tests.repos.helpers import ALICE, BOB, as_user


async def create(client, user_id, name="key"):
    return await client.post(
        "/v1/api-keys/create", json={"name": name}, headers=as_user(user_id)
    )


def without_request_id(headers) -> dict[str, str]:
    return {k: v for k, v in headers.items() if k.lower() != "x-request-id"}


async def authenticates(db, redis, token) -> bool:
    try:
        await validate_api_key(
            token,
            "203.0.113.9",
            cache=RedisAuthCache(redis),
            database=SqlAuthDatabase(db),
            audit=SqlFailureAudit(db),
        )
    except Exception:  # noqa: BLE001 — any refusal counts as "no"
        return False
    return True


# region Ownership


@pytest.mark.parametrize("action", ["revoke", "delete"])
async def test_other_users_key_is_404_and_keeps_working(client, db, redis, action):
    alice_key = (await create(client, ALICE)).json()["data"]

    response = await client.post(
        f"/v1/api-keys/{action}", json={"id": alice_key["id"]}, headers=as_user(BOB)
    )

    assert response.status_code == 404
    assert await authenticates(db, redis, alice_key["key"])
    async with db() as session:
        status = await session.scalar(
            select(ApiKey.status).where(ApiKey.id == alice_key["id"])
        )
        bob_audit = await session.scalar(
            select(func.count()).where(ApiKeyAuditLog.user_id == BOB)
        )
    assert status == "active"
    assert bob_audit == 0


@pytest.mark.parametrize("action", ["revoke", "delete"])
async def test_not_yours_is_byte_identical_to_does_not_exist(client, action):
    alice_key = (await create(client, ALICE)).json()["data"]
    await create(client, BOB)  # Bob exists and has keys of his own

    not_yours = await client.post(
        f"/v1/api-keys/{action}", json={"id": alice_key["id"]}, headers=as_user(BOB)
    )
    missing = await client.post(
        f"/v1/api-keys/{action}",
        json={"id": "01ARZ3NDEKTSV4RRFFQ69G5FAV"},
        headers=as_user(BOB),
    )

    assert not_yours.status_code == missing.status_code == 404
    assert not_yours.content == missing.content
    # X-Request-Id is unique per request by design and says nothing about
    # the key; every other header must match exactly.
    assert without_request_id(not_yours.headers) == without_request_id(missing.headers)


async def test_list_shows_only_your_keys(client):
    await create(client, ALICE, "alice")
    await create(client, BOB, "bob")

    listed = (await client.post("/v1/api-keys/list", headers=as_user(BOB))).json()

    assert [key["name"] for key in listed["data"]] == ["bob"]


async def test_body_cannot_name_a_user(client):
    response = await client.post(
        "/v1/api-keys/create",
        json={"name": "x", "user_id": ALICE},
        headers=as_user(BOB),
    )

    assert response.status_code == 422


# endregion

# region Create


async def test_create_returns_the_key_once_with_a_backend_prefix(client, db, redis):
    response = await create(client, ALICE, "  Production  ")
    data = response.json()["data"]

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert data["name"] == "Production"
    assert data["key_prefix"] == f"mthw01_{data['id']}"
    assert data["key"].startswith(data["key_prefix"] + "_")
    assert await authenticates(db, redis, data["key"])

    secret = data["key"].rsplit("_", 1)[1]
    async with db() as session:
        stored = await session.scalar(
            select(ApiKey.key_hash).where(ApiKey.id == data["id"])
        )
        audit = (await session.execute(select(ApiKeyAuditLog))).scalar_one()
    assert stored == hashlib.sha256(secret.encode()).hexdigest()
    assert (audit.action, audit.target_id, audit.source_ip) == (
        "key.created",
        data["id"],
        "203.0.113.7",
    )


@pytest.mark.parametrize("name", ["", "   ", "x" * 101])
async def test_create_validates_the_name(client, name):
    response = await create(client, ALICE, name)

    assert response.status_code == 422


async def test_ten_concurrent_creates_at_four_of_five_allow_exactly_one(
    client, db, redis
):
    for index in range(MAX_KEYS - 1):
        await create(client, ALICE, f"existing {index}")
    # The race is about the key limit, not the write rate limit: start the
    # ten from a full bucket.
    await redis.delete(bucket_key(ALICE, "write"))

    responses = await asyncio.gather(
        *(create(client, ALICE, f"race {index}") for index in range(10))
    )

    statuses = sorted(response.status_code for response in responses)
    assert statuses == [200] + [409] * 9
    async with db() as session:
        active = await session.scalar(
            select(func.count()).where(
                ApiKey.user_id == ALICE, ApiKey.status == "active"
            )
        )
    assert active == MAX_KEYS
    assert {r.json()["error"]["code"] for r in responses if r.status_code == 409} == {
        "identity_api_key_limit_reached"
    }


async def test_revoked_keys_do_not_count_toward_the_limit(client):
    ids = [(await create(client, ALICE)).json()["data"]["id"] for _ in range(MAX_KEYS)]
    assert (await create(client, ALICE)).status_code == 409

    await client.post(
        "/v1/api-keys/revoke", json={"id": ids[0]}, headers=as_user(ALICE)
    )

    assert (await create(client, ALICE)).status_code == 200


# endregion

# region List


async def test_list_leaks_no_hash_and_no_secret(client, db):
    created = (await create(client, ALICE)).json()["data"]
    secret = created["key"].rsplit("_", 1)[1]
    async with db() as session:
        key_hash = await session.scalar(
            select(ApiKey.key_hash).where(ApiKey.id == created["id"])
        )

    response = await client.post("/v1/api-keys/list", headers=as_user(ALICE))
    body = response.text

    assert "key_hash" not in body
    assert key_hash not in body
    assert created["key"] not in body
    # no fragment of the secret either — any 6-char window of it
    assert not any(secret[i : i + 6] in body for i in range(len(secret) - 5))
    assert set(response.json()["data"][0]) == {
        "id",
        "name",
        "key_prefix",
        "status",
        "created_at",
        "last_used_at",
        "never_used",
    }


async def test_list_is_newest_first_and_hides_deleted(client):
    first = (await create(client, ALICE, "first")).json()["data"]["id"]
    await create(client, ALICE, "second")
    await client.post("/v1/api-keys/delete", json={"id": first}, headers=as_user(ALICE))

    listed = (await client.post("/v1/api-keys/list", headers=as_user(ALICE))).json()

    assert [key["name"] for key in listed["data"]] == ["second"]
    assert listed["data"][0]["never_used"] is True


# endregion

# region Revoke / delete


async def test_revoke_invalidates_cache_and_is_idempotent(client, db, redis):
    created = (await create(client, ALICE)).json()["data"]
    assert await authenticates(db, redis, created["key"])  # now cached
    assert await redis.exists(positive_cache_key(created["id"]))

    first = await client.post(
        "/v1/api-keys/revoke", json={"id": created["id"]}, headers=as_user(ALICE)
    )
    second = await client.post(
        "/v1/api-keys/revoke", json={"id": created["id"]}, headers=as_user(ALICE)
    )

    assert first.status_code == second.status_code == 200
    assert not await redis.exists(positive_cache_key(created["id"]))
    assert not await authenticates(db, redis, created["key"])
    async with db() as session:
        actions = (
            await session.scalars(
                select(ApiKeyAuditLog.action).order_by(ApiKeyAuditLog.id)
            )
        ).all()
    assert actions == ["key.created", "key.revoked"]  # second call changed nothing


async def test_delete_is_idempotent_and_revoke_after_delete_is_404(client, db, redis):
    created = (await create(client, ALICE)).json()["data"]

    for _ in range(2):
        response = await client.post(
            "/v1/api-keys/delete", json={"id": created["id"]}, headers=as_user(ALICE)
        )
        assert response.status_code == 200
    revoke = await client.post(
        "/v1/api-keys/revoke", json={"id": created["id"]}, headers=as_user(ALICE)
    )

    assert revoke.status_code == 404
    assert not await authenticates(db, redis, created["key"])
    async with db() as session:
        row = (
            await session.execute(select(ApiKey).where(ApiKey.id == created["id"]))
        ).scalar_one()
        deletes = await session.scalar(
            select(func.count()).where(ApiKeyAuditLog.action == "key.deleted")
        )
    assert row.status == "deleted" and row.deleted_at is not None
    assert deletes == 1


async def test_failed_cache_invalidation_is_500_never_success(
    client, redis, monkeypatch
):
    created = (await create(client, ALICE)).json()["data"]

    async def broken_invalidate(self, key_id):
        from app.services.validate_api_key import AuthInfrastructureError

        raise AuthInfrastructureError("down")

    monkeypatch.setattr(RedisAuthCache, "invalidate", broken_invalidate)
    response = await client.post(
        "/v1/api-keys/revoke", json={"id": created["id"]}, headers=as_user(ALICE)
    )

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "identity_api_key_revocation_pending"


async def test_unauthenticated_calls_are_401(client):
    app.dependency_overrides.clear()  # back to the real session check

    response = await client.post("/v1/api-keys/list")

    assert response.status_code == 401


# endregion


# region Management rate limit


async def test_writes_are_rate_limited_per_user(client):
    for _ in range(10):  # WRITE_CAPACITY
        await client.post(
            "/v1/api-keys/revoke",
            json={"id": "01ARZ3NDEKTSV4RRFFQ69G5FAV"},
            headers=as_user(ALICE),
        )

    limited = await client.post(
        "/v1/api-keys/revoke",
        json={"id": "01ARZ3NDEKTSV4RRFFQ69G5FAV"},
        headers=as_user(ALICE),
    )
    other_user = await create(client, BOB)
    reads = await client.post("/v1/api-keys/list", headers=as_user(ALICE))

    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "identity_rate_limit_exceeded"
    assert int(limited.headers["Retry-After"]) >= 1
    assert other_user.status_code == 200  # per user, not global
    assert reads.status_code == 200  # reads have their own, larger bucket


# endregion
