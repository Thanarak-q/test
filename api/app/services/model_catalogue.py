"""model_validate and manage_model (docs/planning/chat_pipeline.md).

The whitelist lives in llm_models; enabled models are cached in the Redis
hash `model:enabled`, one field per model name.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.constants.llm import CACHE_INVALIDATION_ATTEMPTS, MODEL_CACHE_TTL_SECONDS
from app.envelope import AppError
from app.repos import audit_repo, model_repo
from app.services.session_auth import Principal, ensure_admin

logger = logging.getLogger(__name__)

MODEL_CACHE_KEY = "model:enabled"

_PROOF = object()


@dataclass(frozen=True)
class ValidatedModel:
    """Proof that model_validate accepted this model.

    Only this module can build one (the private _PROOF token), so a code
    path that skipped validation has nothing to hand proxy_to_llm.
    """

    model_id: int
    name: str
    context_window: int
    max_output_tokens: int
    _proof: object = field(repr=False, compare=False, default=None)

    def __post_init__(self) -> None:
        if self._proof is not _PROOF:
            raise TypeError("ValidatedModel is issued by model_validate only")


def _not_allowed() -> AppError:
    return AppError(
        "llm_model_not_allowed", "This model is not available to your key.", 403
    )


def _issue(row: model_repo.ModelRow) -> ValidatedModel:
    return ValidatedModel(
        model_id=row.id,
        name=row.name,
        context_window=row.context_window,
        max_output_tokens=row.max_output_tokens,
        _proof=_PROOF,
    )


async def model_validate(
    redis: Redis,
    session_factory: async_sessionmaker[AsyncSession],
    raw_name: object,
) -> ValidatedModel:
    """The enabled model with exactly this name, or 400/403.

    There is no default model: a request without one is a 400.
    """
    if not isinstance(raw_name, str) or not raw_name.strip():
        raise AppError("llm_model_required", "`model` is required.", 400)
    name = raw_name.strip()

    cache_ok = True
    try:
        cached = await redis.hget(MODEL_CACHE_KEY, name)
    except RedisError:
        # The one place the chain does not fail closed on Redis: this is a
        # primary-key-sized read of a tiny table, cheap enough to serve from
        # MySQL until Redis is back. (The rest of the chain will 503 anyway.)
        cached, cache_ok = None, False
        logger.warning("model cache unavailable; reading llm_models directly")

    if cached is not None:
        try:
            row = model_repo.ModelRow(**json.loads(cached))
            if row.status == "enabled" and row.name == name:
                return _issue(row)
        except (TypeError, ValueError):
            pass  # a corrupt entry is a miss

    async with session_factory() as session:
        row = await model_repo.get_by_name(session, name=name)
    if row is None or row.status != "enabled":
        raise _not_allowed()

    if cache_ok:
        try:
            async with redis.pipeline(transaction=True) as pipe:
                pipe.hset(MODEL_CACHE_KEY, name, json.dumps(row.__dict__))
                # NX: the TTL runs from the first fill, so an entry is never
                # older than the TTL even while the hash keeps being written.
                pipe.expire(MODEL_CACHE_KEY, MODEL_CACHE_TTL_SECONDS, nx=True)
                await pipe.execute()
        except RedisError:
            logger.warning("model cache write failed")
    return _issue(row)


async def get_enabled_by_id(
    session_factory: async_sessionmaker[AsyncSession], model: ValidatedModel
) -> model_repo.ModelRow:
    """Re-read the model just before the provider call.

    A ValidatedModel proves the model was enabled when validated, not that it
    still is; this closes the window between validation and the call.
    """
    async with session_factory() as session:
        row = await model_repo.get_by_id(session, model_id=model.model_id)
    if row is None or row.status != "enabled":
        raise _not_allowed()
    return row


async def manage_model(
    session: AsyncSession,
    redis: Redis,
    *,
    principal: Principal,
    model_id: int,
    status: str,
    source_ip: str | None,
    request_id: str | None,
) -> None:
    """Enable or disable a model. Admin only — checked here, not just at
    the route, so no caller can reach this without the role."""
    ensure_admin(principal)
    if status not in ("enabled", "disabled"):
        raise AppError("llm_invalid_model_status", "Unknown model status.", 400)

    now = datetime.now(UTC)
    async with session.begin():
        if not await model_repo.set_status(
            session, model_id=model_id, status=status, at=now
        ):
            raise AppError("llm_model_not_found", "Model not found.", 404)
        await audit_repo.record_model_event(
            session,
            actor_id=principal.user_id,
            action="model.enabled" if status == "enabled" else "model.disabled",
            target_id=model_id,
            source_ip=source_ip,
            request_id=request_id,
            at=now,
        )

    # After the commit. Without this a disabled model stays callable until
    # the cache TTL runs out.
    for attempt in range(1, CACHE_INVALIDATION_ATTEMPTS + 1):
        try:
            await redis.delete(MODEL_CACHE_KEY)
            return
        except RedisError:
            if attempt < CACHE_INVALIDATION_ATTEMPTS:
                await asyncio.sleep(0.05 * attempt)
    logger.error(
        "ALERT model cache invalidation failed; model %s may stay callable "
        "for up to %ss",
        model_id,
        MODEL_CACHE_TTL_SECONDS,
    )
    raise AppError(
        "llm_model_change_pending",
        "The change is saved but not in effect yet. Try again.",
        500,
    )
