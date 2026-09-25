from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from redis.asyncio import Redis

from app.config import settings
from app.envelope import EnvelopeRoute, register_error_handlers
from app.routers import api_keys, dashboard, health
from app.services.perkey_rate_limit import check_token_bucket_fits_largest_request
from app.services.proxy_trust import build_trusted_proxy_set
from app.services.session_auth import check_session_config


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    check_token_bucket_fits_largest_request()
    check_session_config()
    # Normalised once here rather than per request: the proxy check sits on
    # the path that exists to reject floods as cheaply as possible.
    app.state.trusted_proxies = build_trusted_proxy_set(settings.trusted_proxy_ips)
    app.state.redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        yield
    finally:
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
