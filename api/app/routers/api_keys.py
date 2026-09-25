from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_unbegun_session
from app.dependencies import get_current_user
from app.envelope import EnvelopeRoute
from app.redis import get_redis
from app.services import api_keys
from app.services.proxy_trust import best_effort_client_ip

router = APIRouter(prefix="/v1/api-keys", tags=["api-keys"], route_class=EnvelopeRoute)

KeyName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]


class _Body(BaseModel):
    # A body carrying user_id (or anything else unexpected) is rejected, not
    # ignored: user_id only ever comes from the session.
    model_config = ConfigDict(extra="forbid")


class CreateKeyRequest(_Body):
    name: KeyName


class KeyIdRequest(_Body):
    id: str = Field(min_length=1, max_length=64)


# Response models are explicit allowlists. key_hash is not a field here and is
# never selected from the database, so adding a column cannot leak it.
class CreatedKeyResponse(BaseModel):
    id: str
    name: str
    key: str = Field(description="Shown once. Not retrievable again.")
    key_prefix: str
    created_at: datetime


class KeySummaryResponse(BaseModel):
    id: str
    name: str
    key_prefix: str
    status: Literal["active", "revoked"]
    created_at: datetime
    last_used_at: datetime | None
    never_used: bool


class OkResponse(BaseModel):
    ok: Literal[True] = True


def _context(request: Request, user_id: int) -> api_keys.RequestContext:
    return api_keys.RequestContext(
        user_id=user_id,
        source_ip=best_effort_client_ip(request, request.app.state.trusted_proxies),
        request_id=getattr(request.state, "request_id", None),
    )


@router.post("/create", operation_id="createApiKey")
async def create_api_key(
    body: CreateKeyRequest,
    request: Request,
    user_id: int = Depends(get_current_user),
    session: AsyncSession = Depends(get_unbegun_session),
) -> CreatedKeyResponse:
    created = await api_keys.create_key(session, _context(request, user_id), body.name)
    return CreatedKeyResponse(
        id=created.id,
        name=created.name,
        key=created.key,
        key_prefix=created.key_prefix,
        created_at=created.created_at,
    )


@router.post("/list", operation_id="listApiKeys")
async def list_api_keys(
    user_id: int = Depends(get_current_user),
    session: AsyncSession = Depends(get_unbegun_session),
) -> list[KeySummaryResponse]:
    return [
        KeySummaryResponse(
            id=key.id,
            name=key.name,
            key_prefix=key.key_prefix,
            status=key.status,
            created_at=key.created_at,
            last_used_at=key.last_used_at,
            never_used=key.never_used,
        )
        for key in await api_keys.list_keys(session, user_id)
    ]


@router.post("/revoke", operation_id="revokeApiKey")
async def revoke_api_key(
    body: KeyIdRequest,
    request: Request,
    user_id: int = Depends(get_current_user),
    session: AsyncSession = Depends(get_unbegun_session),
    redis: Redis = Depends(get_redis),
) -> OkResponse:
    await api_keys.revoke_key(session, redis, _context(request, user_id), body.id)
    return OkResponse()


@router.post("/delete", operation_id="deleteApiKey")
async def delete_api_key(
    body: KeyIdRequest,
    request: Request,
    user_id: int = Depends(get_current_user),
    session: AsyncSession = Depends(get_unbegun_session),
    redis: Redis = Depends(get_redis),
) -> OkResponse:
    await api_keys.delete_key(session, redis, _context(request, user_id), body.id)
    return OkResponse()
