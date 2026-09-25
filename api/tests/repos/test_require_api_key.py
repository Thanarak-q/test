"""The public API's auth dependency, end to end against real Redis and MySQL."""

import httpx
import pytest
from fastapi import Depends, FastAPI

from app.dependencies import require_api_key
from app.envelope import EnvelopeRoute, register_error_handlers
from app.services.pre_auth_rate_limit import CAPACITY, bucket_key
from tests.repos.helpers import ALICE, seed_key

PROXY_HEADERS = {"X-Forwarded-Proto": "https", "X-Real-IP": "198.51.100.4"}


@pytest.fixture
async def api(db, redis):
    app = FastAPI()
    app.router.route_class = EnvelopeRoute
    register_error_handlers(app)
    app.state.redis = redis
    app.state.trusted_proxies = frozenset({"127.0.0.1"})

    @app.get("/whoami")
    async def whoami(identity=Depends(require_api_key)):
        return identity

    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
    async with httpx.AsyncClient(transport=transport, base_url="http://api") as http:
        yield http


async def test_valid_key_returns_identity_and_refunds_the_ip_token(api, db, redis):
    key_id, token = await seed_key(db, user_id=ALICE)

    response = await api.get(
        "/whoami", headers={**PROXY_HEADERS, "Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    assert response.json()["data"] == {"user_id": ALICE, "key_id": key_id}
    tokens = float(await redis.hget(bucket_key("198.51.100.4"), "tokens"))
    assert tokens >= CAPACITY - 0.01  # the success did not cost a failure token


async def test_missing_and_wrong_credentials_get_the_same_401(api, db):
    _, token = await seed_key(db, user_id=ALICE)
    wrong = token[:-1] + ("A" if token[-1] != "A" else "B")

    missing = await api.get("/whoami", headers=PROXY_HEADERS)
    bad = await api.get(
        "/whoami", headers={**PROXY_HEADERS, "Authorization": f"Bearer {wrong}"}
    )

    assert missing.status_code == bad.status_code == 401
    assert missing.content == bad.content
    assert dict(missing.headers) == dict(bad.headers)


async def test_plain_http_is_rejected_before_the_key_is_looked_at(api, db):
    _, token = await seed_key(db, user_id=ALICE)

    response = await api.get(
        "/whoami",
        headers={
            **PROXY_HEADERS,
            "X-Forwarded-Proto": "http",
            "Authorization": f"Bearer {token}",
        },
    )

    assert response.status_code == 400
    assert "revoke this key" in response.json()["error"]["message"]
