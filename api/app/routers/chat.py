"""POST /v1/chat/completions and /v1/embeddings — the OpenAI-compatible
public endpoints.

A plain APIRoute, not EnvelopeRoute: a successful reply must be the OpenAI
response shape, or the OpenAI SDKs cannot read it. Errors still use the
standard envelope (`error.code`, `error.message`), which is what the SDKs
read from an error body.
"""

import json

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from redis.asyncio import Redis

from app.constants.llm import MAX_REQUEST_BODY_BYTES
from app.db import SessionLocal
from app.dependencies import get_llm_http, require_api_key
from app.envelope import AppError
from app.redis import get_redis
from app.services import chat, embeddings
from app.services.validate_api_key import AuthIdentity

router = APIRouter(prefix="/v1", tags=["chat"])


async def _read_body(request: Request) -> object:
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_REQUEST_BODY_BYTES:
        raise AppError("llm_request_too_large", "The request body is too large.", 413)
    raw = bytearray()
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > MAX_REQUEST_BODY_BYTES:
            raise AppError(
                "llm_request_too_large", "The request body is too large.", 413
            )
    try:
        return json.loads(raw)
    except ValueError:
        raise AppError(
            "llm_invalid_request", "The body must be valid JSON.", 400
        ) from None


@router.post(
    "/chat/completions",
    operation_id="createChatCompletion",
    response_model=None,
    include_in_schema=False,  # public API reference lives in /docs, not the web client
)
async def create_chat_completion(
    request: Request,
    # Steps 0–3 run here, before the body is even read: an unauthenticated
    # caller learns nothing about what the body should look like.
    identity: AuthIdentity = Depends(require_api_key),
    redis: Redis = Depends(get_redis),
    http: httpx.AsyncClient = Depends(get_llm_http),
) -> JSONResponse | StreamingResponse:
    idem_key = chat.check_idempotency_key(request.headers.get("Idempotency-Key"))
    body = await _read_body(request)
    reply, headers = await chat.chat_completion(
        body=body,
        user_id=identity["user_id"],
        key_id=identity["key_id"],
        request_id=request.state.request_id,
        idem_key=idem_key,
        redis=redis,
        http=http,
        session_factory=SessionLocal,
    )
    if isinstance(reply, dict):
        return JSONResponse(reply, headers=headers)
    return StreamingResponse(reply, media_type="text/event-stream", headers=headers)


@router.post(
    "/embeddings",
    operation_id="createEmbeddings",
    include_in_schema=False,  # public API reference lives in /docs, not the web client
)
async def create_embeddings(
    request: Request,
    identity: AuthIdentity = Depends(require_api_key),
    redis: Redis = Depends(get_redis),
    http: httpx.AsyncClient = Depends(get_llm_http),
) -> JSONResponse:
    body = await _read_body(request)
    response, headers = await embeddings.create_embeddings(
        body=body,
        user_id=identity["user_id"],
        key_id=identity["key_id"],
        request_id=request.state.request_id,
        redis=redis,
        http=http,
        session_factory=SessionLocal,
    )
    return JSONResponse(response, headers=headers)
