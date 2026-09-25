"""Admin model management over HTTP, and the quota schema health job."""

import httpx
import pytest
from fastapi import Request

from app.dependencies import get_current_principal
from app.jobs.quota_health import check
from app.main import app
from app.services.quota import quota_key
from app.services.session_auth import Principal


@pytest.fixture
async def as_role(db, redis):
    async def principal(request: Request) -> Principal:
        return Principal(user_id=900, role=request.headers["X-Test-Role"])

    app.dependency_overrides[get_current_principal] = principal
    app.state.redis = redis
    app.state.trusted_proxies = frozenset({"127.0.0.1"})
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as http:

        async def post(path, role, body):
            return await http.post(path, json=body, headers={"X-Test-Role": role})

        yield post
    app.dependency_overrides.clear()


async def test_admin_can_disable_and_enable(as_role):
    disabled = await as_role("/v1/admin/models/disable", "admin", {"id": 1})
    enabled = await as_role("/v1/admin/models/enable", "admin", {"id": 1})

    assert disabled.status_code == enabled.status_code == 200


async def test_admin_lists_every_model_including_disabled(as_role):
    await as_role("/v1/admin/models/disable", "admin", {"id": 2})

    response = await as_role("/v1/admin/models/list", "admin", {})

    assert response.status_code == 200
    assert [(m["name"], m["status"]) for m in response.json()["data"]] == [
        ("gpt-4.1", "disabled"),
        ("gpt-4o", "enabled"),
        ("text-embedding-3-small", "enabled"),
    ]


async def test_a_user_cannot_list(as_role):
    response = await as_role("/v1/admin/models/list", "user", {})

    assert response.status_code == 403


async def test_a_user_cannot(as_role):
    response = await as_role("/v1/admin/models/disable", "user", {"id": 1})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "identity_forbidden"


async def test_an_unknown_model_is_404(as_role):
    response = await as_role("/v1/admin/models/disable", "admin", {"id": 999})

    assert response.status_code == 404


async def test_quota_health_check_alerts_on_schema_change(redis, caplog):
    await redis.hset(quota_key(5), mapping={"limit": 1000, "used": 0})
    assert await check(redis, 5) == []

    await redis.hset(quota_key(5), "used", "1,000")
    problems = await check(redis, 5)

    assert problems and "ALERT" in caplog.text


@pytest.fixture
async def public(db, redis):
    app.state.redis = redis
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as http:
        yield http


async def test_public_list_needs_no_auth_and_shows_enabled_only(public, as_role):
    await as_role("/v1/admin/models/disable", "admin", {"id": 2})

    response = await public.get("/v1/public/models")

    assert response.status_code == 200
    assert response.json()["data"] == [
        {
            "name": "gpt-4o",
            "kind": "chat",
            "context_window": 128000,
            "max_output_tokens": 16384,
        },
        {
            "name": "text-embedding-3-small",
            "kind": "embedding",
            "context_window": 8191,
            "max_output_tokens": 0,
        },
    ]


async def test_public_list_follows_admin_changes(public, as_role):
    before = await public.get("/v1/public/models")  # fills the cache
    await as_role("/v1/admin/models/disable", "admin", {"id": 1})

    after = await public.get("/v1/public/models")

    assert "gpt-4o" in [m["name"] for m in before.json()["data"]]
    assert "gpt-4o" not in [m["name"] for m in after.json()["data"]]
