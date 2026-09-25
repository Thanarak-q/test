"""POST /v1/embeddings — the same pipeline as chat (docs/planning/chat_pipeline.md),
minus what does not apply: no output cap, no sampling, no idempotency replay.

Steps 0–3 (HTTPS, client IP, pre-auth limit, key) are the require_api_key
dependency. As in chat, everything that can refuse a request without
spending anything runs before the rate-limit bucket and quota are touched.
"""

import logging
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.constants.llm import MAX_EMBEDDING_INPUTS
from app.constants.perkey_rate_limit import MAX_INPUT_TOKENS
from app.envelope import AppError
from app.services.chat import record_usage, release_quietly
from app.services.model_catalogue import model_validate
from app.services.perkey_rate_limit import perkey_rate_limit
from app.services.provider import CallerIdentity, embed_via_llm
from app.services.quota import quota_reconcile, quota_reserve
from app.services.tokens import estimate_text_tokens

logger = logging.getLogger(__name__)


class EmbeddingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: Any = None
    input: str | list[str]
    # OpenAI SDKs send encoding_format; only float is returned.
    encoding_format: str | None = None
    dimensions: int | None = Field(default=None, ge=1)


def _parse(body: object) -> tuple[EmbeddingsRequest, list[str]]:
    if not isinstance(body, dict):
        raise AppError("llm_invalid_request", "The body must be a JSON object.", 400)
    if body.get("encoding_format") not in (None, "float"):
        raise AppError(
            "llm_unsupported_parameter",
            "`encoding_format` must be float; base64 is not supported.",
            400,
        )
    try:
        request = EmbeddingsRequest.model_validate(body)
    except ValidationError as exc:
        extra = [e["loc"][-1] for e in exc.errors() if e["type"] == "extra_forbidden"]
        if extra:
            raise AppError(
                "llm_unsupported_parameter",
                f"`{extra[0]}` is not supported by this API.",
                400,
            ) from None
        raise AppError(
            "llm_invalid_request",
            "`input` must be a string or a list of strings.",
            400,
        ) from None

    inputs = [request.input] if isinstance(request.input, str) else request.input
    if not inputs or any(not text for text in inputs):
        raise AppError("llm_invalid_request", "`input` must not be empty.", 400)
    if len(inputs) > MAX_EMBEDDING_INPUTS:
        raise AppError(
            "llm_invalid_request",
            f"`input` may hold at most {MAX_EMBEDDING_INPUTS} strings.",
            400,
        )
    return request, inputs


async def create_embeddings(
    *,
    body: object,
    user_id: int,
    key_id: str,
    request_id: str,
    redis: Redis,
    http: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[dict[str, Any], dict[str, str]]:
    """The OpenAI-shaped response body and the headers to send with it."""
    request, inputs = _parse(body)

    model = await model_validate(
        redis, session_factory, request.model, kind="embedding"
    )

    # Each string must fit the model; the request as a whole must fit the
    # same input cap as chat (which the token bucket is sized for).
    per_input = [estimate_text_tokens(text) for text in inputs]
    if max(per_input) > model.context_window:
        raise AppError(
            "llm_context_window_exceeded",
            f"Each input must be at most {model.context_window} tokens.",
            400,
        )
    est = sum(per_input)
    if est > MAX_INPUT_TOKENS:
        raise AppError(
            "llm_input_too_large",
            f"The input is over the {MAX_INPUT_TOKENS}-token limit per request.",
            413,
        )

    limits = await perkey_rate_limit(redis, user_id, est)
    reservation = await quota_reserve(
        redis, user_id=user_id, request_id=request_id, est_tokens=est
    )

    settled = False
    try:
        result = await embed_via_llm(
            http=http,
            session_factory=session_factory,
            caller=CallerIdentity(user_id=user_id, key_id=key_id),
            model=model,
            reservation=reservation,
            inputs=inputs,
            dimensions=request.dimensions,
            est_input=est,
            request_id=request_id,
        )
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

    response = {
        "object": "list",
        "data": [
            {"object": "embedding", "index": index, "embedding": vector}
            for index, vector in enumerate(result.vectors)
        ],
        "model": model.name,
        "usage": {
            "prompt_tokens": result.prompt_tokens,
            "total_tokens": result.prompt_tokens,
        },
    }
    return response, limits.headers()
