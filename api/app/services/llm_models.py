"""Model whitelist: read Redis, fall back to the DB on a miss and cache the result."""

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.llm import MODEL_CACHE_TTL_S
from app.envelope import AppError
from app.repos import llm as llm_repo

_CACHE_KEY = "llm:models:active"


async def allowed_models(redis: Redis, session: AsyncSession) -> set[str]:
    cached = await redis.smembers(_CACHE_KEY)
    if cached:
        return set(cached)

    models = set(await llm_repo.list_active_models(session))
    if models:
        await redis.sadd(_CACHE_KEY, *models)
        await redis.expire(_CACHE_KEY, MODEL_CACHE_TTL_S)
    return models


async def ensure_allowed(redis: Redis, session: AsyncSession, model: str) -> None:
    models = await allowed_models(redis, session)
    if model not in models:
        raise AppError(
            "llm_model_not_allowed",
            f"Model '{model}' is not allowed.",
            status_code=400,
        )
