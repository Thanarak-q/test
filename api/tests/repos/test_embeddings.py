"""POST /v1/embeddings end to end: real MySQL and Redis, the real auth chain,
and a scripted provider behind httpx.MockTransport."""

import json

import httpx
import pytest
from sqlalchemy import select

from app.main import app
from app.models import LlmProviderCallLog, LlmUsageLog
from app.services import provider
from app.services.quota import quota_key, reservation_key
from app.services.tokens import estimate_text_tokens
from tests.repos.helpers import ALICE, seed_key

PROXY = {"X-Forwarded-Proto": "https", "X-Real-IP": "198.51.100.4"}
MODEL = "text-embedding-3-small"


class FakeProvider:
    """Answers /embeddings with one small vector per input."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.status = 200
        self.body: object = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.body is not None:
            return httpx.Response(self.status, content=json.dumps(self.body))
        inputs = json.loads(request.content)["input"]
        prompt = sum(estimate_text_tokens(text) for text in inputs)
        return httpx.Response(
            self.status,
            json={
                "object": "list",
                # Out of order on purpose: the API must sort by index.
                "data": [
                    {"object": "embedding", "index": i, "embedding": [float(i), 0.5]}
                    for i in reversed(range(len(inputs)))
                ],
                "model": MODEL,
                "usage": {"prompt_tokens": prompt, "total_tokens": prompt},
            },
        )

    @property
    def sent(self) -> dict:
        return json.loads(self.requests[-1].content)


@pytest.fixture
def fake():
    return FakeProvider()


@pytest.fixture
async def api(db, redis, fake, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-test-provider")
    monkeypatch.setattr(provider.outbound, "in_flight", 0)
    app.state.redis = redis
    app.state.trusted_proxies = frozenset({"127.0.0.1"})
    app.state.llm_http = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as http:
        yield http
    await app.state.llm_http.aclose()


@pytest.fixture
async def token(db, redis):
    _, token = await seed_key(db, user_id=ALICE)
    await redis.hset(quota_key(ALICE), mapping={"limit": 100_000, "used": 0})
    return token


async def embed(api, token, body=None):
    return await api.post(
        "/v1/embeddings",
        json=body if body is not None else {"model": MODEL, "input": "สวัสดี"},
        headers={**PROXY, "Authorization": f"Bearer {token}"},
    )


async def test_returns_an_openai_response_and_settles_quota(
    api, db, redis, fake, token
):
    response = await embed(api, token, {"model": MODEL, "input": ["a", "bb"]})

    body = response.json()
    assert response.status_code == 200
    assert body["object"] == "list"
    assert body["model"] == MODEL
    assert [item["index"] for item in body["data"]] == [0, 1]
    assert [item["embedding"] for item in body["data"]] == [[0.0, 0.5], [1.0, 0.5]]
    charged = body["usage"]["prompt_tokens"]
    assert body["usage"]["total_tokens"] == charged
    assert int(await redis.hget(quota_key(ALICE), "used")) == charged
    assert await redis.zcard(reservation_key(ALICE)) == 0
    assert fake.sent == {
        "model": MODEL,
        "input": ["a", "bb"],
        "encoding_format": "float",
    }
    assert "RateLimit-Remaining" in response.headers

    async with db() as session:
        usage = (await session.scalars(select(LlmUsageLog))).all()
        calls = (await session.scalars(select(LlmProviderCallLog))).all()
    assert [row.tokens for row in usage] == [charged]
    assert [row.outcome for row in calls] == ["ok"]


async def test_a_single_string_and_dimensions_are_passed_through(api, fake, token):
    response = await embed(
        api, token, {"model": MODEL, "input": "hi", "dimensions": 256}
    )

    assert response.status_code == 200
    assert fake.sent["input"] == ["hi"]
    assert fake.sent["dimensions"] == 256


async def test_needs_a_key(api):
    response = await api.post(
        "/v1/embeddings", json={"model": MODEL, "input": "x"}, headers=PROXY
    )

    assert response.status_code == 401


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"model": "gpt-4o", "input": "x"}, "llm_model_not_allowed"),
        ({"model": "nope", "input": "x"}, "llm_model_not_allowed"),
        ({"input": "x"}, "llm_model_required"),
        ({"model": MODEL, "input": ""}, "llm_invalid_request"),
        ({"model": MODEL, "input": []}, "llm_invalid_request"),
        ({"model": MODEL, "input": [1, 2]}, "llm_invalid_request"),
        ({"model": MODEL, "input": ["x"] * 257}, "llm_invalid_request"),
        ({"model": MODEL, "input": "x", "user": "u"}, "llm_unsupported_parameter"),
        (
            {"model": MODEL, "input": "x", "encoding_format": "base64"},
            "llm_unsupported_parameter",
        ),
    ],
)
async def test_refuses_before_spending(api, redis, fake, token, body, code):
    response = await embed(api, token, body)

    assert 400 <= response.status_code < 500
    assert response.json()["error"]["code"] == code
    assert fake.requests == []
    assert int(await redis.hget(quota_key(ALICE), "used")) == 0


async def test_a_chat_model_cannot_embed_and_an_embedding_model_cannot_chat(api, token):
    chat = await api.post(
        "/v1/chat/completions",
        json={"model": MODEL, "messages": [{"role": "user", "content": "hi"}]},
        headers={**PROXY, "Authorization": f"Bearer {token}"},
    )

    assert chat.status_code == 403
    assert chat.json()["error"]["code"] == "llm_model_not_allowed"


async def test_input_over_the_model_window_is_refused(api, fake, token):
    response = await embed(api, token, {"model": MODEL, "input": "x" * 40_000})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "llm_context_window_exceeded"
    assert fake.requests == []


async def test_input_over_the_request_cap_is_413(api, fake, token):
    response = await embed(api, token, {"model": MODEL, "input": ["x" * 30_000] * 2})

    assert response.status_code == 413
    assert fake.requests == []


async def test_provider_failure_releases_the_reservation(api, redis, fake, token):
    fake.status, fake.body = 500, {"error": "boom"}

    response = await embed(api, token)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "llm_provider_unavailable"
    assert int(await redis.hget(quota_key(ALICE), "used")) == 0
    assert await redis.zcard(reservation_key(ALICE)) == 0


async def test_a_malformed_reply_is_a_502(api, redis, fake, token):
    fake.body = {"data": [{"index": 0, "embedding": "not a vector"}]}

    response = await embed(api, token)

    assert response.status_code == 502
    assert int(await redis.hget(quota_key(ALICE), "used")) == 0


async def test_a_disabled_embedding_model_is_refused(api, db, fake, token, redis):
    from sqlalchemy import update

    from app.models import LlmModel
    from app.services.model_catalogue import MODEL_CACHE_KEY

    async with db.begin() as session:
        await session.execute(
            update(LlmModel).where(LlmModel.name == MODEL).values(status="disabled")
        )
    await redis.delete(MODEL_CACHE_KEY)

    response = await embed(api, token)

    assert response.status_code == 403
    assert fake.requests == []
