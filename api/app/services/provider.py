"""proxy_to_llm — the one place that talks to the model provider.

Content handling: prompts and replies never leave this module except as the
reply handed back to the caller. Nothing here logs content; errors are
re-raised without their payload (`from None`), and the loggable fields are
an allowlist (request_id, key_id, model_id, outcome, token counts, latency).

No automatic retry: the provider bills per call, and retrying without
knowing whether it processed the first attempt risks paying twice. Callers
retry with an Idempotency-Key. A circuit breaker is deferred — the timeout
and concurrency cap already protect the main path; revisit with real
traffic metrics.
"""

import hashlib
import json
import logging
import math
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from pydantic_settings import BaseSettings, SettingsConfigDict
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import metrics
from app.config import settings
from app.constants.llm import (
    ALLOWED_ROLES,
    ESTIMATE_SAFETY_FACTOR,
    IDEMPOTENCY_TTL_SECONDS,
    MAX_OUTBOUND_CONCURRENCY,
    MAX_PROVIDER_RESPONSE_BYTES,
    POLICY_CAP,
    PROVIDER_CONNECT_TIMEOUT_SECONDS,
    PROVIDER_READ_TIMEOUT_SECONDS,
    PROVIDER_WRITE_TIMEOUT_SECONDS,
    USAGE_ESTIMATE_TOLERANCE,
)
from app.constants.perkey_rate_limit import MAX_INPUT_TOKENS
from app.envelope import AppError
from app.repos import provider_call_repo
from app.services.model_catalogue import ValidatedModel, get_enabled_by_id
from app.services.quota import Reservation
from app.services.tokens import estimate_tokens

logger = logging.getLogger(__name__)

PROVIDER_TIMEOUT = httpx.Timeout(
    connect=PROVIDER_CONNECT_TIMEOUT_SECONDS,
    read=PROVIDER_READ_TIMEOUT_SECONDS,
    write=PROVIDER_WRITE_TIMEOUT_SECONDS,
    pool=PROVIDER_CONNECT_TIMEOUT_SECONDS,
)


@dataclass(frozen=True)
class Sampling:
    """Caller-set generation parameters, already bounds-checked."""

    temperature: float | None = None
    top_p: float | None = None


@dataclass(frozen=True)
class CallerIdentity:
    user_id: int
    key_id: str


@dataclass(frozen=True)
class ProviderResult:
    content: str
    finish_reason: str
    prompt_tokens: int
    completion_tokens: int
    # What quota is charged: the provider's total when it validates, else our
    # (slightly high) estimate.
    billable_tokens: int
    replayed: bool = False


# region Concurrency
class _OutboundLimiter:
    """Caps provider calls in flight in this process; refuses instead of
    queueing. Per process by design: it protects this process's workers."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.in_flight = 0

    def acquire(self) -> None:
        if self.in_flight >= self.limit:
            metrics.outbound_rejected.inc()
            raise AppError(
                "llm_capacity_exhausted",
                "The service is at capacity. Retry shortly.",
                503,
            )
        self.in_flight += 1
        metrics.outbound_in_flight.set(self.in_flight)

    def release(self) -> None:
        self.in_flight -= 1
        metrics.outbound_in_flight.set(self.in_flight)


outbound = _OutboundLimiter(MAX_OUTBOUND_CONCURRENCY)
# endregion


# region Credentials
class _DevSecret(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    llm_api_key: str = ""


def _load_api_key() -> str:
    """The provider key, read fresh for this call and never stored.

    Staging and production read a file mounted from the secret store, so a
    rotated key applies on the next request without a restart. Dev and test
    may use LLM_API_KEY from the environment or .env instead.
    """
    if settings.llm_api_key_file:
        try:
            return Path(settings.llm_api_key_file).read_text().strip()
        except OSError:
            logger.error("ALERT provider key file unreadable")
            return ""
    if settings.env in ("dev", "test"):
        return _DevSecret().llm_api_key
    return ""


def check_provider_config() -> None:
    """Refuse to boot staging/production without a key file."""
    if settings.env in ("staging", "production") and not settings.llm_api_key_file:
        raise RuntimeError(
            f"LLM_API_KEY_FILE is required when ENV is {settings.env!r}; the "
            "provider key comes from the secret store, not the environment."
        )


# endregion


def _bad_request(code: str, message: str) -> AppError:
    return AppError(code, message, 400)


def _validate_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    if not messages:
        raise _bad_request("llm_invalid_messages", "`messages` must not be empty.")
    clean = []
    for message in messages:
        role, content = message.get("role"), message.get("content")
        if role not in ALLOWED_ROLES:
            raise _bad_request(
                "llm_invalid_role",
                "Each message role must be system, user or assistant.",
            )
        if not isinstance(content, str):
            raise _bad_request(
                "llm_invalid_messages", "Each message content must be a string."
            )
        clean.append({"role": role, "content": content})
    return clean


def payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def idempotency_key(key_id: str, idem_key: str) -> str:
    return f"idem:{key_id}:{idem_key}"


def validate_usage(
    raw: object, *, est_input: int, cap_tokens: int
) -> tuple[int, int, int, bool]:
    """(prompt, completion, billable, valid) from the provider's usage.

    Invalid usage — missing, not integers, not adding up, completion over
    the cap we sent, or prompt more than ±50% from our estimate — is replaced
    by our estimate, leaning slightly high, and logged.
    """
    usage = raw if isinstance(raw, dict) else {}
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    total = usage.get("total_tokens")
    ints = all(
        isinstance(value, int) and not isinstance(value, bool)
        for value in (prompt, completion, total)
    )
    valid = (
        ints
        and prompt > 0
        and completion >= 0
        and total == prompt + completion
        and completion <= cap_tokens
        and abs(prompt - est_input) <= USAGE_ESTIMATE_TOLERANCE * est_input
    )
    if valid:
        metrics.estimate_gap.observe(prompt / est_input)
        return prompt, completion, total, True

    metrics.usage_validation_failures.inc()
    estimated_prompt = math.ceil(est_input * ESTIMATE_SAFETY_FACTOR)
    logger.warning(
        "provider usage failed validation; charging estimate",
        extra={
            "reported": {
                "prompt_tokens": prompt if ints else None,
                "completion_tokens": completion if ints else None,
            },
            "estimated_prompt_tokens": estimated_prompt,
            "cap_tokens": cap_tokens,
        },
    )
    return estimated_prompt, cap_tokens, estimated_prompt + cap_tokens, False


async def proxy_to_llm(
    *,
    http: httpx.AsyncClient,
    redis: Redis,
    session_factory: async_sessionmaker[AsyncSession],
    caller: CallerIdentity,
    model: ValidatedModel,
    reservation: Reservation,
    messages: list[dict[str, Any]],
    cap_tokens: int,
    sampling: Sampling,
    request_id: str,
    idem_key: str | None,
) -> ProviderResult:
    # model and reservation are proofs issued by model_validate and
    # quota_reserve; a caller that skipped either has nothing to pass here.
    if not isinstance(model, ValidatedModel) or not isinstance(
        reservation, Reservation
    ):
        raise TypeError("proxy_to_llm needs a ValidatedModel and a Reservation")

    record = await get_enabled_by_id(session_factory, model)

    clean = _validate_messages(messages)
    cap_tokens = min(cap_tokens, POLICY_CAP, record.max_output_tokens)
    est_input = estimate_tokens(clean)
    if est_input > MAX_INPUT_TOKENS:
        raise AppError(
            "llm_input_too_large",
            f"The prompt is over the {MAX_INPUT_TOKENS}-token input limit.",
            413,
        )
    if est_input + cap_tokens > record.context_window:
        raise _bad_request(
            "llm_context_window_exceeded",
            "The prompt plus max_tokens does not fit this model's context window.",
        )

    # A structured object: user input is only ever a value, never spliced
    # into a string. No system instruction is added.
    payload: dict[str, Any] = {
        "model": record.name,
        "messages": clean,
        "max_tokens": cap_tokens,
    }
    if sampling.temperature is not None:
        payload["temperature"] = sampling.temperature
    if sampling.top_p is not None:
        payload["top_p"] = sampling.top_p
    digest = payload_hash(payload)

    if idem_key is not None:
        replay = await _replay(redis, caller.key_id, idem_key, digest)
        if replay is not None:
            return replay

    outbound.acquire()
    started = time.monotonic()
    outcome = "provider_error"
    prompt_tokens = completion_tokens = None
    try:
        status, body = await _call_provider(http, payload)
        outcome, parsed = _interpret(status, body)
        prompt_tokens, completion_tokens, billable, _ = validate_usage(
            parsed.get("usage"), est_input=est_input, cap_tokens=cap_tokens
        )
        result = ProviderResult(
            content=parsed["content"],
            finish_reason=parsed["finish_reason"],
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            billable_tokens=billable,
        )
    except _Outcome as failure:
        outcome = failure.outcome
        raise failure.error from None
    finally:
        outbound.release()
        latency_ms = int((time.monotonic() - started) * 1000)
        metrics.provider_calls.labels(outcome=outcome).inc()
        await _log_call(
            session_factory,
            caller=caller,
            request_id=request_id,
            model_id=record.id,
            outcome=outcome,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
        )

    if idem_key is not None:
        await _store_replay(redis, caller.key_id, idem_key, digest, result)
    return result


# region Provider HTTP
class _Outcome(Exception):
    """An outcome for the call log plus the neutral error the caller sees."""

    def __init__(self, outcome: str, error: AppError) -> None:
        self.outcome = outcome
        self.error = error


def _unavailable(outcome: str) -> _Outcome:
    return _Outcome(
        outcome,
        AppError(
            "llm_provider_unavailable",
            "The model provider is unavailable. Retry shortly.",
            503,
        ),
    )


def _bad_gateway(outcome: str) -> _Outcome:
    return _Outcome(
        outcome,
        AppError(
            "llm_provider_bad_response",
            "The model provider returned an unusable response.",
            502,
        ),
    )


async def _call_provider(
    http: httpx.AsyncClient, payload: dict[str, Any]
) -> tuple[int, bytes]:
    api_key = _load_api_key()
    if not api_key:
        logger.error("ALERT no provider API key configured")
        raise _unavailable("provider_error")
    try:
        async with http.stream(
            "POST",
            f"{settings.llm_base_url.rstrip('/')}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=PROVIDER_TIMEOUT,
        ) as response:
            declared = response.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > MAX_PROVIDER_RESPONSE_BYTES:
                raise _bad_gateway("too_large")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body += chunk
                if len(body) > MAX_PROVIDER_RESPONSE_BYTES:
                    raise _bad_gateway("too_large")
            return response.status_code, bytes(body)
    except httpx.TimeoutException:
        raise _unavailable("timeout") from None
    except httpx.HTTPError:
        raise _unavailable("provider_error") from None


def _interpret(status: int, body: bytes) -> tuple[str, dict[str, Any]]:
    """Map the provider's reply to our outcome; never forward its error body."""
    if status == 429:
        # The provider's limit, not the caller's: a 429 would tell them to
        # slow down when it is our upstream that is saturated.
        raise _unavailable("rate_limited")
    if status >= 500:
        raise _unavailable("provider_error")
    if status != 200:
        raise _bad_gateway("provider_error")
    try:
        data = json.loads(body)
        choice = data["choices"][0]
        content = choice["message"]["content"]
        finish_reason = choice.get("finish_reason") or "stop"
        if not isinstance(content, str) or not isinstance(finish_reason, str):
            raise TypeError
    except (ValueError, KeyError, IndexError, TypeError):
        raise _bad_gateway("bad_response") from None
    return "ok", {
        "content": content,
        "finish_reason": finish_reason,
        "usage": data.get("usage"),
    }


# endregion


# region Idempotency
async def _replay(
    redis: Redis, key_id: str, idem_key: str, digest: str
) -> ProviderResult | None:
    try:
        stored = await redis.get(idempotency_key(key_id, idem_key))
    except RedisError as exc:
        raise AppError(
            "service_unavailable", "The service is temporarily unavailable.", 503
        ) from exc
    if stored is None:
        return None
    record = json.loads(stored)
    if record["payload_hash"] != digest:
        raise _bad_request(
            "llm_idempotency_conflict",
            "This Idempotency-Key was already used with a different request.",
        )
    metrics.idempotent_replays.inc()
    return ProviderResult(**record["result"], replayed=True)


async def _store_replay(
    redis: Redis, key_id: str, idem_key: str, digest: str, result: ProviderResult
) -> None:
    record = {
        "payload_hash": digest,
        "result": {
            "content": result.content,
            "finish_reason": result.finish_reason,
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "billable_tokens": result.billable_tokens,
        },
    }
    try:
        await redis.set(
            idempotency_key(key_id, idem_key),
            json.dumps(record),
            ex=IDEMPOTENCY_TTL_SECONDS,
        )
    except RedisError:
        # The call succeeded and is billed; losing the replay record only
        # means a retry with the same key calls the provider again.
        logger.warning("idempotency record not stored", extra={"key_id": key_id})


# endregion


async def _log_call(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    caller: CallerIdentity,
    request_id: str,
    model_id: int,
    outcome: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    latency_ms: int,
) -> None:
    fields = {
        "request_id": request_id,
        "key_id": caller.key_id,
        "model_id": model_id,
        "outcome": outcome,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "latency_ms": latency_ms,
    }
    logger.info("provider call", extra=fields)
    try:
        async with session_factory.begin() as session:
            await provider_call_repo.record(
                session, user_id=caller.user_id, at=datetime.now(UTC), **fields
            )
    except Exception:  # noqa: BLE001 — the call already happened; never mask it
        logger.error("ALERT provider call log not written", extra=fields)
