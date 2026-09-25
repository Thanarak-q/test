from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.retention import USAGE_RETENTION_DAYS
from app.db import get_session
from app.dependencies import get_current_user
from app.envelope import EnvelopeRoute
from app.redis import get_redis
from app.services import dashboard

router = APIRouter(prefix="/v1", tags=["dashboard"], route_class=EnvelopeRoute)


class QuotaResponse(BaseModel):
    limit: int
    used: int
    remaining: int


class TotalsResponse(BaseModel):
    requests: int
    tokens: int


class DailyUsageResponse(BaseModel):
    date: date
    requests: int
    tokens: int


class SourceUsageResponse(BaseModel):
    source: Literal["api", "web"]
    requests: int
    tokens: int


class KeyUsageResponse(BaseModel):
    key_id: str
    name: str
    key_prefix: str
    status: Literal["active", "revoked", "deleted"]
    requests: int
    tokens: int
    request_share_pct: float


class UsageResponse(BaseModel):
    date_from: date = Field(serialization_alias="from")
    date_to: date = Field(serialization_alias="to")
    timezone: str
    clamped: bool = Field(
        description="True when the requested range was cut to the retention window."
    )
    # Remaining quota is shown here and nowhere else. The public API never
    # returns it: the quota is shared with the main app, and an API caller may
    # not be the account owner.
    quota: QuotaResponse
    totals: TotalsResponse
    by_source: list[SourceUsageResponse]
    by_key: list[KeyUsageResponse]
    daily: list[DailyUsageResponse]


@router.get("/usage", operation_id="getUsage", response_model_by_alias=True)
async def get_usage(
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    days: int | None = Query(
        None,
        ge=1,
        le=USAGE_RETENTION_DAYS,
        description="Without `from`: the last N days ending at `to` (default today).",
    ),
    key_id: str | None = Query(None, max_length=26),
    user_id: int = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> UsageResponse:
    report = await dashboard.usage_report(
        session,
        redis,
        user_id=user_id,
        date_from=date_from,
        date_to=date_to,
        days=days,
        key_id=key_id,
    )
    return UsageResponse.model_validate(report, from_attributes=True)
