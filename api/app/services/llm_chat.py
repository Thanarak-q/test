"""Chat pipeline: preauth → validate → rate limit → quota → model → provider."""

import time
from typing import Any

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants.llm import CHARS_PER_TOKEN, PER_MESSAGE_TOKEN_OVERHEAD
from app.repos import llm as llm_repo
from app.services import llm_models, llm_provider, llm_quota
from app.services.rate_limit import check_rate_limit

Usage = dict[str, int]


def preauth(api_key: str | None) -> int:
    # ponytail: no key store yet — every caller is the single default user. Swap for
    # a hashed-key lookup returning the owning user_id when multi-user lands.
    return settings.llm_default_user_id


def estimate_tokens(messages: list[dict[str, str]], max_tokens: int | None) -> int:
    prompt = sum(
        len(m["content"]) // CHARS_PER_TOKEN + PER_MESSAGE_TOKEN_OVERHEAD
        for m in messages
    )
    return prompt + (max_tokens or settings.llm_output_reserve)


def _usage_of(completion: dict[str, Any]) -> Usage:
    usage = completion.get("usage") or {}
    prompt = int(usage.get("prompt_tokens") or 0)
    output = int(usage.get("completion_tokens") or 0)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": output,
        "total_tokens": int(usage.get("total_tokens") or prompt + output),
    }


async def chat(
    session: AsyncSession,
    redis: Redis,
    *,
    api_key: str | None,
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> dict[str, Any]:
    user_id = preauth(api_key)
    await check_rate_limit(redis, str(user_id))

    reservation = await llm_quota.reserve(
        redis, session, user_id, estimate_tokens(messages, max_tokens)
    )
    try:
        await llm_models.ensure_allowed(redis, session, model)

        options = {
            key: value
            for key, value in (("max_tokens", max_tokens), ("temperature", temperature))
            if value is not None
        }
        started = time.perf_counter()
        completion = await llm_provider.complete(model, messages, **options)
        latency_ms = int((time.perf_counter() - started) * 1000)
    except Exception:
        await llm_quota.release(redis, reservation)
        raise

    usage = _usage_of(completion)
    # A provider that reports no usage still cost something — charge the estimate
    # rather than settling to zero and handing out a free call.
    await llm_quota.settle(
        redis, session, reservation, usage["total_tokens"] or reservation.estimate
    )
    await llm_repo.insert_usage_log(
        session, user_id=user_id, model=model, latency_ms=latency_ms, **usage
    )

    choice = (completion.get("choices") or [{}])[0]
    return {
        "id": completion.get("id", ""),
        "model": completion.get("model", model),
        "content": (choice.get("message") or {}).get("content") or "",
        "finish_reason": choice.get("finish_reason"),
        "usage": usage,
    }
