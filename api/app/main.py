import logging
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.exc import DisconnectionError, InterfaceError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from app.config import settings
from app.constants.infra import (
    REDIS_CONNECT_TIMEOUT_SECONDS,
    REDIS_SOCKET_TIMEOUT_SECONDS,
)
from app.constants.llm import MAX_OUTBOUND_CONCURRENCY
from app.envelope import EnvelopeRoute, error_response, register_error_handlers
from app.routers import admin_models, api_keys, chat, dashboard, health, public_models
from app.services.perkey_rate_limit import check_token_bucket_fits_largest_request
from app.services.provider import PROVIDER_TIMEOUT, check_provider_config
from app.services.proxy_trust import build_trusted_proxy_set
from app.services.session_auth import check_session_config


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    check_token_bucket_fits_largest_request()
    check_session_config()
    check_provider_config()
    # Normalised once here rather than per request: the proxy check sits on
    # the path that exists to reject floods as cheaply as possible.
    app.state.trusted_proxies = build_trusted_proxy_set(settings.trusted_proxy_ips)
    app.state.redis = Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=REDIS_CONNECT_TIMEOUT_SECONDS,
        socket_timeout=REDIS_SOCKET_TIMEOUT_SECONDS,
    )
    # One client for every provider call: its pool is the outbound
    # concurrency cap, so connections are reused rather than re-handshaken.
    app.state.llm_http = httpx.AsyncClient(
        timeout=PROVIDER_TIMEOUT,
        limits=httpx.Limits(
            max_connections=MAX_OUTBOUND_CONCURRENCY,
            max_keepalive_connections=MAX_OUTBOUND_CONCURRENCY,
        ),
    )
    try:
        yield
    finally:
        await app.state.llm_http.aclose()
        await app.state.redis.aclose()


app = FastAPI(title="matthew-api", lifespan=lifespan)
app.router.route_class = EnvelopeRoute

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=settings.allowed_hosts,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    # This API authenticates with a bearer token, not cookies. Allowing
    # credentials would make browsers attach the site's cookies to
    # cross-origin calls, which buys nothing and widens the attack surface.
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    # Without this, browser callers cannot read the rate limit headers they
    # need to back off correctly, or the request id they need to report a
    # problem.
    expose_headers=[
        "X-Request-Id",
        "RateLimit-Limit",
        "RateLimit-Remaining",
        "RateLimit-Reset",
        "X-RateLimit-Tokens-Limit",
        "X-RateLimit-Tokens-Remaining",
        "X-RateLimit-Tokens-Reset",
        "Retry-After",
    ],
)


@app.middleware("http")
async def add_cache_headers(request: Request, call_next):
    """Keep every response out of shared and browser caches.

    Applied centrally so a new endpoint cannot be added without it.
    """
    response = await call_next(request)
    response.headers.setdefault("Cache-Control", "no-store")
    response.headers.setdefault("Pragma", "no-cache")
    return response


_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}\Z")


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    """Tag every request with an id that users can quote and audit rows carry.

    An incoming X-Request-Id is kept only from the trusted proxy (so nginx's
    $request_id ties its logs to ours); from anyone else it is replaced, so a
    caller cannot write arbitrary text into our logs.
    """
    incoming = request.headers.get("X-Request-Id", "")
    peer = request.client.host if request.client else None
    trusted = peer in getattr(request.app.state, "trusted_proxies", frozenset())
    request_id = (
        incoming if trusted and _REQUEST_ID.match(incoming) else uuid.uuid4().hex
    )
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-Id"] = request_id
    return response


register_error_handlers(app)

_logger = logging.getLogger(__name__)

# docs/NON_FUNCTIONAL.md §3.3: an unavailable dependency is 503 — never a 500
# that reads like a bug, and never a 401/404 that tells users their key or
# key id is wrong. Only connectivity errors: an IntegrityError is a bug and
# stays a 500.
_INFRASTRUCTURE_ERRORS = (
    OperationalError,
    InterfaceError,
    DisconnectionError,
    PoolTimeoutError,
    RedisError,
)


async def _infrastructure_unavailable(request: Request, exc: Exception):
    _logger.error(
        "dependency unavailable on %s %s: %r",
        request.method,
        request.url.path,
        exc,
    )
    return error_response(
        "service_unavailable",
        "The service is temporarily unavailable. Try again shortly.",
        503,
    )


for _error in _INFRASTRUCTURE_ERRORS:
    app.add_exception_handler(_error, _infrastructure_unavailable)

# Each API router declares its own prefix and route class
# (`APIRouter(prefix="/v1/...", route_class=EnvelopeRoute)`), so a router's
# path is readable from its own file. The route class must be on the router:
# include_router keeps each route's own class, so setting it on app.router
# alone leaves included routes unwrapped.
#
# Health is the exception. Operational, not part of the API surface: no
# version prefix, no auth, and it must not touch Redis, the database, or the
# provider — otherwise it becomes an unauthenticated way to load them.
app.include_router(health.router)
app.include_router(api_keys.router)
app.include_router(dashboard.router)
app.include_router(chat.router)
app.include_router(admin_models.router)
app.include_router(public_models.router)


@app.get("/metrics", include_in_schema=False)
async def metrics(request: Request) -> Response:
    """Prometheus scrape endpoint. Operational, like /health: unversioned and
    unenveloped. Served only to localhost and the trusted proxy — never to
    the public, since counts of outcomes and limits help someone probing."""
    peer = request.client.host if request.client else None
    allowed = {"127.0.0.1", "::1"} | request.app.state.trusted_proxies
    if peer not in allowed:
        return Response(status_code=404)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
