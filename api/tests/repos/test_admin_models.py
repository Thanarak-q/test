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
