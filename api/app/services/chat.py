"""POST /v1/chat/completions, steps 4–11 of docs/planning/chat_pipeline.md.

Steps 0–3 (HTTPS, client IP, pre-auth limit, key) are the require_api_key
dependency. The order below is deliberate: everything that can refuse a
request without spending anything (parameter checks, model validation) runs
before the caller's rate-limit bucket and quota are touched.
"""

import json
import logging
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import anyio
import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.constants.llm import POLICY_CAP, UNSUPPORTED_PARAMS
from app.envelope import AppError
from app.repos import usage_repo
from app.services.model_catalogue import ValidatedModel, model_validate
from app.services.perkey_rate_limit import perkey_rate_limit
from app.services.provider import (
    CallerIdentity,
    LlmStream,
    ProviderResult,
    Sampling,
    open_llm_stream,
    proxy_to_llm,
)
from app.services.quota import (
    Reservation,
    quota_reconcile,
    quota_release,
    quota_reserve,
)
from app.services.tokens import estimate_tokens

logger = logging.getLogger(__name__)

_IDEMPOTENCY_KEY = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")


class _Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str
    content: Any


class _StreamOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    include_usage: bool = False


class ChatRequest(BaseModel):
    """The accepted request. Anything else is refused, not ignored: every
    parameter that reaches the provider has been bounds-checked here."""

    model_config = ConfigDict(extra="forbid")

    model: Any = None
    messages: list[_Message] = Field(min_length=1)
    max_tokens: int | None = Field(default=None, ge=1)
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, ge=0, le=1)
    # OpenAI SDKs may send n=1 by default; anything else is refused below.
    n: int | None = None
    stream: bool | None = None
    stream_options: _StreamOptions | None = None


def _unsupported(name: str) -> AppError:
    return AppError(
        "llm_unsupported_parameter",
        f"`{name}` is not supported by this API.",
        400,
    )


def _parse(body: object) -> ChatRequest:
    if not isinstance(body, dict):
        raise AppError("llm_invalid_request", "The body must be a JSON object.", 400)

    # Step 4: refuse unsupported parameters by name.
    for name in UNSUPPORTED_PARAMS:
        if name in body:
            raise _unsupported(name)
    if body.get("n") not in (None, 1):
        raise _unsupported("n > 1")

    try:
        request = ChatRequest.model_validate(body)
    except ValidationError as exc:
        extra = [e["loc"][-1] for e in exc.errors() if e["type"] == "extra_forbidden"]
        if extra:
            raise _unsupported(str(extra[0])) from None
        where = ".".join(str(part) for part in exc.errors()[0]["loc"])
        raise AppError(
            "llm_invalid_request", f"Invalid value for `{where}`.", 400
        ) from None
    if request.stream_options is not None and not request.stream:
        raise AppError(
            "llm_invalid_request",
            "`stream_options` is only allowed when `stream` is true.",
            400,
        )
    return request


def check_idempotency_key(raw: str | None) -> str | None:
    if raw is None:
        return None
    if not _IDEMPOTENCY_KEY.match(raw):
        raise AppError(
            "llm_invalid_idempotency_key",
            "Idempotency-Key must be 1–128 letters, digits or ._:-",
            400,
        )
    return raw


@dataclass(frozen=True)
class _Admitted:
    request: ChatRequest
    messages: list[dict[str, Any]]
    model: ValidatedModel
    cap: int
    limits: Any
    reservation: Reservation


async def _admit(
    *,
    body: object,
    user_id: int,
    request_id: str,
    redis: Redis,
    session_factory: async_sessionmaker[AsyncSession],
) -> _Admitted:
    """Steps 4–9, shared by the plain and the streamed reply."""
    request = _parse(body)
    messages = [message.model_dump() for message in request.messages]

    # Step 5: cheaper than the rate limit (a cache hit almost always), and a
    # bad model is refused without spending the caller's bucket.
    model = await model_validate(redis, session_factory, request.model, kind="chat")

    # Step 6: the output cap.
    cap = min(
        request.max_tokens or model.max_output_tokens,
        model.max_output_tokens,
        POLICY_CAP,
    )

    # Step 7: one estimate, used by both the rate limit and the reservation.
    # Malformed messages are refused with a clear 400 inside the provider
    # call; here they simply count as empty.
    est = (
        estimate_tokens(
            m
            for m in messages
            if isinstance(m["role"], str) and isinstance(m["content"], str)
        )
        + cap
    )

    # Step 8.
    limits = await perkey_rate_limit(redis, user_id, est)

    # Step 9.
    reservation = await quota_reserve(
        redis, user_id=user_id, request_id=request_id, est_tokens=est
    )
    return _Admitted(request, messages, model, cap, limits, reservation)


async def chat_completion(
    *,
    body: object,
    user_id: int,
    key_id: str,
    request_id: str,
    idem_key: str | None,
    redis: Redis,
    http: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[dict[str, Any] | AsyncIterator[bytes], dict[str, str]]:
    """The reply and the headers to send with it: an OpenAI-shaped body, or
    the server-sent event stream when the request asked for `stream`."""
    admitted = await _admit(
        body=body,
        user_id=user_id,
        request_id=request_id,
        redis=redis,
        session_factory=session_factory,
    )
    request, model, reservation = (
        admitted.request,
        admitted.model,
        admitted.reservation,
    )
    call = {
        "http": http,
        "redis": redis,
        "session_factory": session_factory,
        "caller": CallerIdentity(user_id=user_id, key_id=key_id),
        "model": model,
        "reservation": reservation,
        "messages": admitted.messages,
        "cap_tokens": admitted.cap,
        "sampling": Sampling(temperature=request.temperature, top_p=request.top_p),
        "request_id": request_id,
        "idem_key": idem_key,
    }

    if request.stream:
        include_usage = bool(
            request.stream_options and request.stream_options.include_usage
        )
        try:
            opened = await open_llm_stream(**call)
        except BaseException:
            await release_quietly(redis, reservation)
            raise
        if isinstance(opened, ProviderResult):  # an idempotent replay
            await release_quietly(redis, reservation)
            events = _replay_events(
                opened,
                request_id=request_id,
                model_name=model.name,
                include_usage=include_usage,
            )
        else:
            events = _stream_events(
                opened,
                reservation=reservation,
                redis=redis,
                session_factory=session_factory,
                user_id=user_id,
                key_id=key_id,
                request_id=request_id,
                model_name=model.name,
                include_usage=include_usage,
            )
        return events, {**admitted.limits.headers(), **SSE_HEADERS}

    # Step 10. The reservation is released on every path that does not
    # settle it — including errors nobody has written yet.
    settled = False
    try:
        result = await proxy_to_llm(**call)
        if not result.replayed:
            settled = await quota_reconcile(redis, reservation, result.billable_tokens)
            await record_usage(
                session_factory,
                user_id=user_id,
                key_id=key_id,
                tokens=result.billable_tokens,
                request_id=request_id,
            )
    finally:
        if not settled:
            await release_quietly(redis, reservation)

    # Step 11: OpenAI-compatible.
    response = {
        "id": f"chatcmpl-{request_id}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model.name,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": result.content},
                "finish_reason": result.finish_reason,
            }
        ],
        "usage": _usage(result),
    }
    return response, admitted.limits.headers()


# region Streaming
SSE_HEADERS = {
    "Cache-Control": "no-cache",
    # nginx buffers proxied responses by default, which would hold every
    # chunk until the reply is complete.
    "X-Accel-Buffering": "no",
}


def _usage(result: ProviderResult) -> dict[str, int]:
    return {
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "total_tokens": result.prompt_tokens + result.completion_tokens,
    }


def _event(data: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


_DONE = b"data: [DONE]\n\n"


def _chunk(
    base: dict[str, Any], delta: dict[str, str], finish_reason: str | None = None
) -> bytes:
    return _event(
        {
            **base,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        }
    )


def _chunk_base(request_id: str, model_name: str) -> dict[str, Any]:
    return {
        "id": f"chatcmpl-{request_id}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model_name,
    }


async def _replay_events(
    result: ProviderResult, *, request_id: str, model_name: str, include_usage: bool
) -> AsyncIterator[bytes]:
    """A stored reply, sent as one content chunk."""
    base = _chunk_base(request_id, model_name)
    yield _chunk(base, {"role": "assistant", "content": result.content})
    yield _chunk(base, {}, result.finish_reason)
    if include_usage:
        yield _event({**base, "choices": [], "usage": _usage(result)})
    yield _DONE


async def _stream_events(
    upstream: LlmStream,
    *,
    reservation: Reservation,
    redis: Redis,
    session_factory: async_sessionmaker[AsyncSession],
    user_id: int,
    key_id: str,
    request_id: str,
    model_name: str,
    include_usage: bool,
) -> AsyncIterator[bytes]:
    """Steps 10–11 for a streamed reply, in the OpenAI chunk format.

    The status line is already sent, so a failure mid-stream is reported as
    an `error` event (the OpenAI SDKs raise on it) and the stream ends
    without [DONE]. However the stream ends — finished, failed, or the caller
    hanging up — the finally block settles quota: the validated total when
    the reply finished, what was produced so far when it did not, nothing
    when no text came back.
    """
    base = _chunk_base(request_id, model_name)
    settled = False
    try:
        yield _chunk(base, {"role": "assistant", "content": ""})
        async for text in upstream.deltas():
            yield _chunk(base, {"content": text})
        result = upstream.result
        assert result is not None
        settled = await quota_reconcile(redis, reservation, result.billable_tokens)
        await record_usage(
            session_factory,
            user_id=user_id,
            key_id=key_id,
            tokens=result.billable_tokens,
            request_id=request_id,
        )
        yield _chunk(base, {}, result.finish_reason)
        if include_usage:
            yield _event({**base, "choices": [], "usage": _usage(result)})
        yield _DONE
    except AppError as exc:
        yield _event({"error": {"code": exc.code, "message": exc.message}})
    finally:
        # Shielded: a client disconnect cancels this task, and the cleanup
        # must still run to the end.
        with anyio.CancelScope(shield=True):
            await upstream.aclose()
            if not settled:
                await _settle_partial(
                    upstream,
                    reservation=reservation,
                    redis=redis,
                    session_factory=session_factory,
                    user_id=user_id,
                    key_id=key_id,
                    request_id=request_id,
                )


async def _settle_partial(
    upstream: LlmStream,
    *,
    reservation: Reservation,
    redis: Redis,
    session_factory: async_sessionmaker[AsyncSession],
    user_id: int,
    key_id: str,
    request_id: str,
) -> None:
    tokens = upstream.partial_billable()
    if tokens:
        try:
            if await quota_reconcile(redis, reservation, tokens):
                await record_usage(
                    session_factory,
                    user_id=user_id,
                    key_id=key_id,
                    tokens=tokens,
                    request_id=request_id,
                )
                return
        except Exception:  # noqa: BLE001 — fall through to the release
            logger.error("partial stream not charged", extra={"request_id": request_id})
    await release_quietly(redis, reservation)


# endregion


async def release_quietly(redis: Redis, reservation) -> None:
    try:
        await quota_release(redis, reservation)
    except Exception:  # noqa: BLE001 — never mask the error being handled
        # The reservation expires on its own within the window.
        logger.error(
            "quota release failed; reservation expires on its own",
            extra={"request_id": reservation.request_id},
        )


async def record_usage(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: int,
    key_id: str,
    tokens: int,
    request_id: str,
) -> None:
    """usage_log, in its own short transaction after quota is settled.

    Not in the request's transaction and never fatal: the provider call is
    done and the quota charged, so the caller gets their reply either way.
    A failure here is an alert — the dashboard would under-report.
    """
    try:
        async with session_factory.begin() as session:
            await usage_repo.record(
                session,
                user_id=user_id,
                source="api",
                key_id=key_id,
                tokens=tokens,
                request_id=request_id,
                at=datetime.now(UTC),
            )
    except Exception:  # noqa: BLE001
        logger.error("ALERT usage log not written", extra={"request_id": request_id})
