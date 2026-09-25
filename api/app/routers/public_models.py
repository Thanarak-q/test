from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from redis.asyncio import Redis

from app.db import SessionLocal
from app.envelope import EnvelopeRoute
from app.redis import get_redis
from app.services import model_catalogue

# Public: the docs site lists models to visitors who have no key. Read-only,
# enabled models only, and served from cache (see model_catalogue.list_public).
router = APIRouter(prefix="/v1/public", tags=["public"], route_class=EnvelopeRoute)


class PublicModelResponse(BaseModel):
    name: str
    kind: Literal["chat", "embedding"]
    context_window: int
    max_output_tokens: int


@router.get("/models", operation_id="listPublicModels")
async def list_public_models(
    redis: Redis = Depends(get_redis),
) -> list[PublicModelResponse]:
    return [
        PublicModelResponse(
            name=model.name,
            kind=model.kind,
            context_window=model.context_window,
            max_output_tokens=model.max_output_tokens,
        )
        for model in await model_catalogue.list_public(redis, SessionLocal)
    ]
