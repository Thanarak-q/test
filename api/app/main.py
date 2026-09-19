from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from redis.asyncio import Redis

from app.config import settings
from app.envelope import EnvelopeRoute, register_error_handlers
from app.routers import health
from app.services import llm_provider
from app.services.proxy_trust import build_trusted_proxy_set


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Normalised once here rather than per request: the proxy check sits on
    # the path that exists to reject floods as cheaply as possible.
    app.state.trusted_proxies = build_trusted_proxy_set(settings.trusted_proxy_ips)
    app.state.redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        yield
    finally:
        await llm_provider.aclose()
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


register_error_handlers(app)

# Operational, not part of the API surface: no version prefix, no auth, and
# it must not touch Redis, the database, or the provider — otherwise it
# becomes an unauthenticated way to load them.
app.include_router(health.router)
