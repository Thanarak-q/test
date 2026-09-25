"""FastAPI dependencies shared across routers."""

from fastapi import Depends, Request
from redis.asyncio import Redis

from app.redis import get_redis
from app.services.api_key_auth import authenticate
from app.services.pre_auth_rate_limit import (
    check_pre_auth_rate_limit,
    refund_pre_auth_token,
)
from app.services.proxy_trust import get_client_ip, require_https
from app.services.session_auth import Principal, resolve_principal
from app.services.validate_api_key import AuthIdentity, invalid_credential

_BEARER = "bearer "


async def require_api_key(
    request: Request,
    redis: Redis = Depends(get_redis),
) -> AuthIdentity:
    """The public API's authentication, in the order the threat model fixes.

    HTTPS and the trusted proxy first (nothing else is trustworthy before),
    then the per-IP limiter (so a flood of random keys never reaches Redis
    lookups or MySQL), then the key. The identity returned is the only place
    a public-API handler may take user_id from.
    """
    peer = require_https(request, request.app.state.trusted_proxies)
    client_ip = get_client_ip(request, peer)
    await check_pre_auth_rate_limit(redis, client_ip)

    authorization = request.headers.get("Authorization", "")
    if not authorization.lower().startswith(_BEARER):
        # Same 401 as every other credential failure.
        raise invalid_credential()

    identity = await authenticate(
        authorization[len(_BEARER) :].strip(), client_ip, redis
    )
    await refund_pre_auth_token(redis, client_ip)
    return identity


async def get_current_principal(request: Request) -> Principal:
    """The verified dashboard caller, or 401."""
    return await resolve_principal(request)


async def get_current_user(
    principal: Principal = Depends(get_current_principal),
) -> int:
    """The verified dashboard user's id, or 401."""
    return principal.user_id
