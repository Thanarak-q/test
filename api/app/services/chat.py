"""POST /v1/chat/completions, steps 4–11 of docs/planning/chat_pipeline.md.

Steps 0–3 (HTTPS, client IP, pre-auth limit, key) are the require_api_key
dependency. The order below is deliberate: everything that can refuse a
request without spending anything (parameter checks, model validation) runs
before the caller's rate-limit bucket and quota are touched.
"""

import logging
import re
import time
from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.constants.llm import POLICY_CAP, UNSUPPORTED_PARAMS
from app.envelope import AppError
from app.repos import usage_repo
from app.services.model_catalogue import model_validate
from app.services.perkey_rate_limit import perkey_rate_limit
from app.services.provider import CallerIdentity, Sampling, proxy_to_llm
from app.services.quota import quota_reconcile, quota_release, quota_reserve
from app.services.tokens import estimate_tokens

logger = logging.getLogger(__name__)

_IDEMPOTENCY_KEY = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")


class _Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str
    content: Any


class ChatRequest(BaseModel):
    """The accepted request. Anything else is refused, not ignored: every
    parameter that reaches the provider has been bounds-checked here."""

    model_config = ConfigDict(extra="forbid")

    model: Any = None
    messages: list[_Message] = Field(min_length=1)
    max_tokens: int | None = Field(default=None, ge=1)
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, ge=0, le=1)
    n: int | None = None
    # OpenAI SDKs may send these with their defaults; only the defaults are
    # accepted (stream=false, n=1), anything else is refused below.
    stream: bool | None = None


def _unsupported(name: str) -> AppError:
    return AppError(
        "llm_unsupported_parameter",
        f"`{name}` is not supported by this API.",
        400,
    )


def _parse(body: object) -> ChatRequest:
    if not isinstance(body, dict):
        raise AppError("llm_invalid_request", "The body must be a JSON object.", 400)

    # Step 4: refuse unsupported parameters by name. An ignored stream=true
    # would leave the SDK waiting for chunks that never arrive.
    if body.get("stream") not in (None, False):
        raise _unsupported("stream")
    for name in UNSUPPORTED_PARAMS:
        if name != "stream" and name in body:
            raise _unsupported(name)
    if body.get("n") not in (None, 1):
        raise _unsupported("n > 1")

    try:
        return ChatRequest.model_validate(body)
    except ValidationError as exc:
        extra = [e["loc"][-1] for e in exc.errors() if e["type"] == "extra_forbidden"]
        if extra:
            raise _unsupported(str(extra[0])) from None
        where = ".".join(str(part) for part in exc.errors()[0]["loc"])
        raise AppError(
            "llm_invalid_request", f"Invalid value for `{where}`.", 400
        ) from None


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
) -> tuple[dict[str, Any], dict[str, str]]:
    """The OpenAI-shaped response body and the headers to send with it."""
    request = _parse(body)
    messages = [message.model_dump() for message in request.messages]

    # Step 5: cheaper than the rate limit (a cache hit almost always), and a
    # bad model is refused without spending the caller's bucket.
    model = await model_validate(redis, session_factory, request.model)

    # Step 6: the output cap.
    cap = min(
        request.max_tokens or model.max_output_tokens,
        model.max_output_tokens,
        POLICY_CAP,
    )

    # Step 7: one estimate, used by both the rate limit and the reservation.
    # Malformed messages are refused with a clear 400 inside proxy_to_llm;
    # here they simply count as empty.
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

    # Step 10. The reservation is released on every path that does not
    # settle it — including errors nobody has written yet.
    settled = False
    try:
        result = await proxy_to_llm(
            http=http,
            redis=redis,
            session_factory=session_factory,
            caller=CallerIdentity(user_id=user_id, key_id=key_id),
            model=model,
            reservation=reservation,
            messages=messages,
            cap_tokens=cap,
            sampling=Sampling(temperature=request.temperature, top_p=request.top_p),
            request_id=request_id,
            idem_key=idem_key,
        )
        if not result.replayed:
            settled = await quota_reconcile(redis, reservation, result.billable_tokens)
            await _record_usage(
                session_factory,
                user_id=user_id,
                key_id=key_id,
                tokens=result.billable_tokens,
                request_id=request_id,
            )
    finally:
        if not settled:
            await _release_quietly(redis, reservation)

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
        "usage": {
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "total_tokens": result.prompt_tokens + result.completion_tokens,
        },
    }
    return response, limits.headers()


async def _release_quietly(redis: Redis, reservation) -> None:
    try:
        await quota_release(redis, reservation)
    except Exception:  # noqa: BLE001 — never mask the error being handled
        # The reservation expires on its own within the window.
        logger.error(
            "quota release failed; reservation expires on its own",
            extra={"request_id": reservation.request_id},
        )


async def _record_usage(
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
