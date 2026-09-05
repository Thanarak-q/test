from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.llm import MAX_CONTENT_CHARS, MAX_MESSAGES
from app.db import get_session
from app.envelope import EnvelopeRoute
from app.redis import get_redis
from app.services import llm_chat

router = APIRouter(tags=["llm"], route_class=EnvelopeRoute)


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=MAX_CONTENT_CHARS)


class ChatRequest(BaseModel):
    model: str = Field(min_length=1, max_length=64)
    messages: list[ChatMessage] = Field(min_length=1, max_length=MAX_MESSAGES)
    max_tokens: int | None = Field(default=None, gt=0, le=32_000)
    temperature: float | None = Field(default=None, ge=0, le=2)


class ChatUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatResponse(BaseModel):
    id: str
    model: str
    content: str
    finish_reason: str | None = None
    usage: ChatUsage


@router.post("/chat")
async def chat(
    body: ChatRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
    authorization: Annotated[str | None, Header()] = None,
) -> ChatResponse:
    result = await llm_chat.chat(
        session,
        redis,
        api_key=_bearer_token(authorization),
        model=body.model,
        messages=[m.model_dump() for m in body.messages],
        max_tokens=body.max_tokens,
        temperature=body.temperature,
    )
    return ChatResponse.model_validate(result)


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.strip().split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return authorization.strip()
