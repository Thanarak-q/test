"""POST /v1/chat/completions end to end: real MySQL and Redis, the real auth
chain, and a scripted provider behind httpx.MockTransport."""

import json
import math

import httpx
import pytest
from sqlalchemy import select, update

from app.main import app
from app.models import LlmModel, LlmProviderCallLog, LlmUsageLog
from app.services import provider
from app.services.quota import quota_key, reservation_key
from app.services.tokens import estimate_tokens
from tests.repos.helpers import ALICE, seed_key

PROXY = {"X-Forwarded-Proto": "https", "X-Real-IP": "198.51.100.4"}
MESSAGES = [{"role": "user", "content": "Say hello in Thai."}]


class FakeProvider:
    """Records requests and replies with whatever the test sets."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.status = 200
        self.body: object = None
        self.raise_: Exception | None = None
        self.usage = {"prompt_tokens": 0, "completion_tokens": 3, "total_tokens": 0}
        # Streamed replies: the text pieces, and raw SSE lines to send instead.
        self.pieces = ["สวั", "สดี"]
        self.stream_lines: list[str] | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.raise_:
            raise self.raise_
        if self.body is not None:
            content = (
                self.body if isinstance(self.body, bytes) else json.dumps(self.body)
            )
            return httpx.Response(self.status, content=content)
        sent = json.loads(request.content)
        prompt = estimate_tokens(sent["messages"])  # a provider that agrees with us
        usage = {**self.usage}
        usage["prompt_tokens"] = usage["prompt_tokens"] or prompt
        usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
        if sent.get("stream"):
            return httpx.Response(
                self.status,
                content="".join(f"{line}\n\n" for line in self._sse(usage)),
                headers={"content-type": "text/event-stream"},
            )
        return httpx.Response(
            self.status,
            json={
                "id": "provider-id",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "สวัสดี"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": usage,
            },
        )

    def _sse(self, usage: dict) -> list[str]:
        if self.stream_lines is not None:
            return self.stream_lines

        def chunk(choices: list, **more) -> str:
            return "data: " + json.dumps(
                {"id": "provider-id", "choices": choices, **more}
            )

        return [
            *(
                chunk([{"index": 0, "delta": {"content": p}, "finish_reason": None}])
                for p in self.pieces
            ),
            chunk([{"index": 0, "delta": {}, "finish_reason": "stop"}]),
            chunk([], usage=usage),
            "data: [DONE]",
        ]

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


async def chat(api, token, body=None, **headers):
    return await api.post(
        "/v1/chat/completions",
        json=body if body is not None else {"model": "gpt-4o", "messages": MESSAGES},
        headers={**PROXY, "Authorization": f"Bearer {token}", **headers},
    )


async def _call_logs(db):
    async with db() as session:
        return (await session.scalars(select(LlmProviderCallLog))).all()


# region Happy path


async def test_returns_an_openai_response_and_settles_quota(
    api, db, redis, fake, token
):
    response = await chat(api, token)

    body = response.json()
    assert response.status_code == 200
    assert body["object"] == "chat.completion"
    assert isinstance(body["created"], int)
    assert body["model"] == "gpt-4o"
    assert body["choices"] == [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "สวัสดี"},
            "finish_reason": "stop",
        }
    ]
    assert "success" not in body  # not wrapped in the envelope
    for header in (
        "RateLimit-Limit",
        "RateLimit-Remaining",
        "X-RateLimit-Tokens-Remaining",
        "X-Request-Id",
    ):
        assert header in response.headers

    total = body["usage"]["total_tokens"]
    assert await redis.hget(quota_key(ALICE), "used") == str(total)
    assert await redis.zcard(reservation_key(ALICE)) == 0
    async with db() as session:
        usage = (await session.execute(select(LlmUsageLog))).scalar_one()
    assert (usage.source, usage.tokens, usage.request_id) == (
        "api",
        total,
        response.headers["X-Request-Id"],
    )
    (log,) = await _call_logs(db)
    assert (log.outcome, log.completion_tokens) == ("ok", 3)


async def test_sends_only_bounded_fields_and_the_key_from_the_secret(api, fake, token):
    await chat(
        api,
        token,
        {"model": "gpt-4o", "messages": MESSAGES, "max_tokens": 99_999, "top_p": 0.5},
    )

    assert fake.sent == {
        "model": "gpt-4o",
        "messages": MESSAGES,
        "max_tokens": 4_096,  # min(99_999, model max output, POLICY_CAP)
        "top_p": 0.5,
    }
    assert fake.requests[-1].headers["Authorization"] == "Bearer sk-test-provider"


# endregion

# region Refused before spending anything


@pytest.mark.parametrize(
    ("extra", "named"),
    [
        ({"tools": []}, "tools"),
        ({"functions": []}, "functions"),
        ({"n": 2}, "n > 1"),
        ({"logit_bias": {}}, "logit_bias"),
    ],
)
async def test_unsupported_parameters_are_refused_by_name(
    api, redis, fake, token, extra, named
):
    response = await chat(
        api, token, {"model": "gpt-4o", "messages": MESSAGES, **extra}
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "llm_unsupported_parameter"
    assert named in response.json()["error"]["message"]
    assert fake.requests == []
    assert await redis.exists(f"rl:req:{ALICE}") == 0  # bucket untouched


async def test_the_sdk_defaults_are_accepted(api, token):
    response = await chat(
        api, token, {"model": "gpt-4o", "messages": MESSAGES, "stream": False, "n": 1}
    )

    assert response.status_code == 200


async def test_an_unknown_model_is_403_without_spending_the_bucket(
    api, redis, fake, token
):
    response = await chat(api, token, {"model": "gpt-5", "messages": MESSAGES})

    assert response.status_code == 403
    assert fake.requests == []
    assert await redis.exists(f"rl:req:{ALICE}") == 0


async def test_a_missing_model_is_400(api, token):
    response = await chat(api, token, {"messages": MESSAGES})

    assert response.json()["error"]["code"] == "llm_model_required"


async def test_authentication_comes_before_the_body(api):
    response = await api.post(
        "/v1/chat/completions", content=b"{not json", headers=PROXY
    )

    assert response.status_code == 401


async def test_an_oversized_body_is_413(api, token):
    response = await chat(
        api,
        token,
        {"model": "gpt-4o", "messages": [{"role": "user", "content": "x" * 1_100_000}]},
    )

    assert response.status_code == 413


# endregion

# region Quota


async def test_quota_exceeded_is_422_and_never_calls_the_provider(
    api, redis, fake, token
):
    await redis.hset(quota_key(ALICE), mapping={"limit": 10, "used": 0})

    response = await chat(api, token)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "llm_quota_exceeded"
    assert fake.requests == []


@pytest.mark.parametrize(
    ("setup", "status", "outcome"),
    [
        (lambda f: setattr(f, "raise_", httpx.ReadTimeout("slow")), 503, "timeout"),
        (
            lambda f: setattr(f, "raise_", httpx.ConnectError("down")),
            503,
            "provider_error",
        ),
        (lambda f: setattr(f, "status", 429), 503, "rate_limited"),
        (lambda f: setattr(f, "status", 500), 503, "provider_error"),
        (lambda f: setattr(f, "status", 400), 502, "provider_error"),
        (lambda f: setattr(f, "body", b"<html>nope"), 502, "bad_response"),
    ],
)
async def test_provider_failures_release_quota_and_are_logged(
    api, db, redis, fake, token, setup, status, outcome
):
    setup(fake)

    response = await chat(api, token)

    assert response.status_code == status
    assert await redis.hget(quota_key(ALICE), "used") == "0"
    assert await redis.zcard(reservation_key(ALICE)) == 0
    (log,) = await _call_logs(db)
    assert log.outcome == outcome


async def test_the_provider_error_body_is_never_forwarded(api, fake, token):
    fake.status = 400
    fake.body = {"error": {"message": "secret upstream detail sk-live-123"}}

    response = await chat(api, token)

    assert "secret upstream detail" not in response.text
    assert "sk-live" not in response.text


async def test_an_oversized_provider_response_is_502(api, redis, fake, token):
    fake.body = b"x" * (10 * 1024 * 1024 + 1)

    response = await chat(api, token)

    assert response.status_code == 502
    assert await redis.zcard(reservation_key(ALICE)) == 0


async def test_implausible_usage_is_replaced_by_the_estimate(api, redis, fake, token):
    fake.usage = {"prompt_tokens": 1, "completion_tokens": 3, "total_tokens": 0}

    response = await chat(api, token)

    est_input = estimate_tokens(MESSAGES)
    charged = math.ceil(est_input * 1.1) + 4_096
    assert response.status_code == 200
    assert await redis.hget(quota_key(ALICE), "used") == str(charged)


async def test_a_high_but_well_formed_count_is_charged_not_the_lower_estimate(
    api, redis, fake, token
):
    # Token-dense text: far over our estimate, so implausible, but charging
    # the estimate would undercharge what the provider billed.
    fake.usage = {"prompt_tokens": 10_000, "completion_tokens": 3, "total_tokens": 0}

    response = await chat(api, token, {**_streamed(), "stream": False})

    assert response.status_code == 200
    assert await redis.hget(quota_key(ALICE), "used") == "10003"


# endregion

# region Checks inside proxy_to_llm


async def test_an_unknown_role_is_400_and_releases_quota(api, redis, fake, token):
    response = await chat(
        api,
        token,
        {"model": "gpt-4o", "messages": [{"role": "tool", "content": "x"}]},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "llm_invalid_role"
    assert fake.requests == []
    assert await redis.zcard(reservation_key(ALICE)) == 0


async def test_a_prompt_that_does_not_fit_the_context_window_is_400(
    api, db, redis, fake, token
):
    async with db.begin() as session:
        await session.execute(
            update(LlmModel)
            .where(LlmModel.name == "gpt-4o")
            .values(context_window=50, max_output_tokens=40)
        )

    response = await chat(api, token)

    assert response.json()["error"]["code"] == "llm_context_window_exceeded"
    assert fake.requests == []


async def test_a_model_disabled_after_validation_is_refused(
    api, db, redis, fake, token
):
    await chat(api, token)  # fills the model cache while enabled
    async with db.begin() as session:
        await session.execute(
            update(LlmModel).where(LlmModel.name == "gpt-4o").values(status="disabled")
        )

    response = await chat(api, token)  # validated from the cache, re-read by id

    assert response.status_code == 403
    assert len(fake.requests) == 1


async def test_the_concurrency_cap_refuses_at_once(
    api, redis, fake, token, monkeypatch
):
    monkeypatch.setattr(provider.outbound, "limit", 0)

    response = await chat(api, token)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "llm_capacity_exhausted"
    assert fake.requests == []
    assert await redis.zcard(reservation_key(ALICE)) == 0


async def test_no_provider_key_is_503(api, fake, token, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "")

    response = await chat(api, token)

    assert response.status_code == 503
    assert fake.requests == []


# endregion

# region Idempotency


async def test_a_repeated_idempotency_key_replays_without_a_second_call(
    api, redis, fake, token
):
    first = await chat(api, token, **{"Idempotency-Key": "retry-1"})
    used_after_first = await redis.hget(quota_key(ALICE), "used")
    second = await chat(api, token, **{"Idempotency-Key": "retry-1"})

    assert second.status_code == 200
    assert second.json()["choices"] == first.json()["choices"]
    assert len(fake.requests) == 1
    assert await redis.hget(quota_key(ALICE), "used") == used_after_first
    assert await redis.zcard(reservation_key(ALICE)) == 0


async def test_the_same_key_with_a_different_body_is_400(api, fake, token):
    await chat(api, token, **{"Idempotency-Key": "retry-2"})

    response = await chat(
        api,
        token,
        {"model": "gpt-4o", "messages": [{"role": "user", "content": "different"}]},
        **{"Idempotency-Key": "retry-2"},
    )

    assert response.json()["error"]["code"] == "llm_idempotency_conflict"
    assert len(fake.requests) == 1


# endregion


# region Streaming


def _events(response: httpx.Response) -> list[object]:
    """The data of each SSE event; [DONE] as the string."""
    events = []
    for block in response.text.split("\n\n"):
        if block.startswith("data: "):
            data = block[len("data: ") :]
            events.append(data if data == "[DONE]" else json.loads(data))
    return events


def _streamed(body: dict | None = None) -> dict:
    return {"model": "gpt-4o", "messages": MESSAGES, "stream": True, **(body or {})}


async def test_a_streamed_reply_is_openai_chunks_and_settles_quota(
    api, db, redis, fake, token
):
    response = await chat(
        api, token, _streamed({"stream_options": {"include_usage": True}})
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "RateLimit-Remaining" in response.headers
    assert fake.sent["stream"] is True
    assert fake.sent["stream_options"] == {"include_usage": True}
    *chunks, usage_event, done = _events(response)
    assert done == "[DONE]"
    assert {c["object"] for c in chunks} == {"chat.completion.chunk"}
    assert chunks[0]["choices"][0]["delta"] == {"role": "assistant", "content": ""}
    text = "".join(c["choices"][0]["delta"].get("content", "") for c in chunks)
    assert text == "สวัสดี"
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"
    assert usage_event["choices"] == []

    total = usage_event["usage"]["total_tokens"]
    assert await redis.hget(quota_key(ALICE), "used") == str(total)
    assert await redis.zcard(reservation_key(ALICE)) == 0
    async with db() as session:
        usage = (await session.execute(select(LlmUsageLog))).scalar_one()
    assert usage.tokens == total
    (log,) = await _call_logs(db)
    assert log.outcome == "ok"
    assert provider.outbound.in_flight == 0


async def test_usage_is_only_streamed_when_asked(api, token):
    events = _events(await chat(api, token, _streamed()))

    assert events[-1] == "[DONE]"
    assert all("usage" not in e for e in events[:-1])


async def test_stream_options_without_stream_is_400(api, fake, token):
    response = await chat(
        api,
        token,
        {"model": "gpt-4o", "messages": MESSAGES, "stream_options": {}},
    )

    assert response.status_code == 400
    assert fake.requests == []


async def test_a_provider_status_error_is_a_plain_error_before_streaming(
    api, db, redis, fake, token
):
    fake.status = 500

    response = await chat(api, token, _streamed())

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "llm_provider_unavailable"
    assert await redis.zcard(reservation_key(ALICE)) == 0
    assert await redis.hget(quota_key(ALICE), "used") == "0"
    (log,) = await _call_logs(db)
    assert log.outcome == "provider_error"
    assert provider.outbound.in_flight == 0


async def test_a_broken_stream_ends_with_an_error_event_and_charges_what_was_sent(
    api, db, redis, fake, token
):
    fake.stream_lines = [
        "data: "
        + json.dumps(
            {
                "choices": [
                    {"index": 0, "delta": {"content": "สวัส"}, "finish_reason": None}
                ]
            }
        ),
        "data: {not json",
    ]

    response = await chat(api, token, _streamed())

    assert response.status_code == 200
    events = _events(response)
    assert events[-1] == {
        "error": {
            "code": "llm_provider_bad_response",
            "message": "The model provider returned an unusable response.",
        }
    }
    assert "[DONE]" not in events
    assert await redis.zcard(reservation_key(ALICE)) == 0
    assert int(await redis.hget(quota_key(ALICE), "used")) > 0
    (log,) = await _call_logs(db)
    assert log.outcome == "bad_response"
    assert provider.outbound.in_flight == 0


async def test_a_stream_that_fails_before_any_text_still_charges_the_prompt(
    api, redis, fake, token
):
    # The provider accepted the request, so it may bill the prompt; a caller
    # hanging up before the first text must not make the call free.
    fake.stream_lines = ["data: [DONE]"]  # no finish_reason, no text

    events = _events(await chat(api, token, _streamed()))

    assert events[-1]["error"]["code"] == "llm_provider_bad_response"
    prompt = math.ceil(estimate_tokens(MESSAGES) * 1.1)
    assert await redis.hget(quota_key(ALICE), "used") == str(prompt)
    assert await redis.zcard(reservation_key(ALICE)) == 0


async def test_a_streamed_reply_replays_under_its_idempotency_key(
    api, redis, fake, token
):
    first = await chat(api, token, _streamed(), **{"Idempotency-Key": "stream-1"})
    used = await redis.hget(quota_key(ALICE), "used")
    second = await chat(api, token, _streamed(), **{"Idempotency-Key": "stream-1"})
    plain = await chat(api, token, **{"Idempotency-Key": "stream-1"})

    def text(response):
        return "".join(
            e["choices"][0]["delta"].get("content", "")
            for e in _events(response)
            if isinstance(e, dict) and e.get("choices")
        )

    assert text(second) == text(first) == "สวัสดี"
    assert _events(second)[-1] == "[DONE]"
    assert plain.json()["choices"][0]["message"]["content"] == "สวัสดี"
    assert len(fake.requests) == 1
    assert await redis.hget(quota_key(ALICE), "used") == used
    assert await redis.zcard(reservation_key(ALICE)) == 0


# endregion


async def test_metrics_are_served_to_localhost_only(api, token):
    await chat(api, token)

    local = await api.get("/metrics")
    app.state.trusted_proxies = frozenset({"10.9.9.9"})
    outside = await httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("203.0.113.5", 1)),
        base_url="http://localhost",
    ).get("/metrics")
    via_proxy = await httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("10.9.9.9", 1)),
        base_url="http://localhost",
    ).get("/metrics")

    assert local.status_code == 200
    assert 'llm_provider_calls_total{outcome="ok"}' in local.text
    assert outside.status_code == 404
    # Whatever the proxy forwards arrives from its IP; it must not unlock this.
    assert via_proxy.status_code == 404
