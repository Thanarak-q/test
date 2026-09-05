from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.envelope import EnvelopeRoute
from app.redis import get_redis

router = APIRouter(tags=["health"], route_class=EnvelopeRoute)


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/db")
async def health_db(session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    await session.execute(text("SELECT 1"))
    return {"status": "ok"}


@router.get("/health/redis")
async def health_redis(redis: Redis = Depends(get_redis)) -> dict[str, str]:
    await redis.ping()
    return {"status": "ok"}
