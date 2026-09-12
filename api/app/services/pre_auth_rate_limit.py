"""IP rate limiting that runs before API key validation."""

import ipaddress
from collections.abc import Iterable

from fastapi import HTTPException, Request
from redis.asyncio import Redis
from redis.exceptions import RedisError

CAPACITY = 60  # capacity of token bucket; shared IPs may serve many devices
REFILL_PER_SECOND = 1  # refill token in token bucket
BUCKET_TTL_SECONDS = 300  # no incoming request from that ip for 5 mins -> delete bucket

# KEYS[1]=bucket  ARGV: capacity, refill_per_second, ttl
_BUCKET_LUA = """
local capacity = tonumber(ARGV[1])
local refill_per_second = tonumber(ARGV[2])
local ttl = tonumber(ARGV[3])
local redis_time = redis.call('TIME')
local now_ms = (tonumber(redis_time[1]) * 1000)
    + math.floor(tonumber(redis_time[2]) / 1000)

local tokens = tonumber(redis.call('HGET', KEYS[1], 'tokens')) or capacity
local last_ms = tonumber(redis.call('HGET', KEYS[1], 'last_ms')) or now_ms
local elapsed_ms = math.max(now_ms - last_ms, 0)
tokens = math.min(tokens + (elapsed_ms * refill_per_second) / 1000, capacity)

local allowed = 0
local retry_after = 0
if tokens >= 1 then
  allowed = 1
  tokens = tokens - 1
else
  retry_after = math.ceil((1 - tokens) / refill_per_second)
end

redis.call('HSET', KEYS[1], 'tokens', tokens, 'last_ms', now_ms)
redis.call('EXPIRE', KEYS[1], ttl)
return {allowed, math.floor(tokens), retry_after}
"""


# other service call this function
async def enforce_pre_auth_rate_limit(
    request: Request, redis: Redis, trusted_proxy_ips: Iterable[str]
) -> None:
    await check_pre_auth_rate_limit(
        redis, get_trusted_proxy_ip(request, trusted_proxy_ips)
    )


async def check_pre_auth_rate_limit(redis: Redis, ip: str) -> None:
    try:
        allowed, _, retry_after = await redis.eval(
            _BUCKET_LUA,
            1,  # redis key amount
            f"rl:ip:{ip}",  # redis key
            CAPACITY,  # AVRG[1]
            REFILL_PER_SECOND,
            BUCKET_TTL_SECONDS,
        )
    except RedisError as exc:
        raise HTTPException(
            status_code=503,
            detail="Rate limiting is temporarily unavailable.",
        ) from exc

    # if not allowed
    if int(allowed) == 0:
        retry_seconds = max(int(retry_after), 1)
        raise HTTPException(
            status_code=429,
            detail=f"Too many requests. Retry in {retry_seconds}s.",
            headers={
                "RateLimit-Limit": str(CAPACITY),
                "RateLimit-Remaining": "0",
                "RateLimit-Reset": str(retry_seconds),
                "Retry-After": str(retry_seconds),
            },
        )


def get_trusted_proxy_ip(request: Request, trusted_proxy_ips: Iterable[str]) -> str:
    # check proxy IP -> nginx
    proxy_ip = request.client.host if request.client else None
    if proxy_ip not in _trusted_proxy_addresses(trusted_proxy_ips):
        raise HTTPException(
            status_code=400,
            detail="A trusted proxy is required.",
        )
    # X-Real-IP from nginx
    client_ip = request.headers.get("X-Real-IP")
    if client_ip is None:
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for is not None:
            client_ip = forwarded_for.rsplit(",", 1)[-1].strip()

    if client_ip is None:
        raise HTTPException(
            status_code=400,
            detail="A trusted client IP is required.",
        )

    try:
        return str(ipaddress.ip_address(client_ip))
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="A valid client IP is required.",
        ) from exc


def _trusted_proxy_addresses(trusted_proxy_ips: Iterable[str]) -> set[str]:
    return {str(ipaddress.ip_address(address)) for address in trusted_proxy_ips}
