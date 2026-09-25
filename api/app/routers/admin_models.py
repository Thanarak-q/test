from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_unbegun_session
from app.dependencies import get_current_principal
from app.envelope import EnvelopeRoute
from app.redis import get_redis
from app.services import model_catalogue
from app.services.proxy_trust import best_effort_client_ip
from app.services.session_auth import Principal

router = APIRouter(prefix="/v1/admin/models", tags=["admin"], route_class=EnvelopeRoute)


class ModelIdRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int


class ModelChangeResponse(BaseModel):
    ok: bool = True


async def _set_status(
    status: str,
    body: ModelIdRequest,
    request: Request,
    principal: Principal,
    session: AsyncSession,
    redis: Redis,
) -> ModelChangeResponse:
    # The role is checked again inside manage_model; this route alone is
    # not what keeps non-admins out.
    await model_catalogue.manage_model(
        session,
        redis,
        principal=principal,
        model_id=body.id,
        status=status,
        source_ip=best_effort_client_ip(request, request.app.state.trusted_proxies),
        request_id=getattr(request.state, "request_id", None),
    )
    return ModelChangeResponse()


@router.post("/enable", operation_id="enableModel")
async def enable_model(
    body: ModelIdRequest,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_unbegun_session),
    redis: Redis = Depends(get_redis),
) -> ModelChangeResponse:
    return await _set_status("enabled", body, request, principal, session, redis)


@router.post("/disable", operation_id="disableModel")
async def disable_model(
    body: ModelIdRequest,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_unbegun_session),
    redis: Redis = Depends(get_redis),
) -> ModelChangeResponse:
    return await _set_status("disabled", body, request, principal, session, redis)
