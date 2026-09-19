"""IP rate limiting that runs before API key validation."""

import ipaddress
from collections.abc import Iterable
from dataclasses import dataclass

from fastapi import HTTPException, Request
from redis.asyncio import Redis
from redis.exceptions import RedisError

CAPACITY = 60  # capacity of token bucket; shared IPs may serve many devices
REFILL_PER_SECOND = 1.0  # refill token in token bucket
BUCKET_TTL_SECONDS = 300  # no incoming request from that ip for 5 mins -> delete bucket

# KEYS[1]=bucket  ARGV: capacity, refill_per_second, ttl, cost
# cost=1 consumes a token; cost=-1 returns one (never above capacity)
_BUCKET_LUA = """
local capacity = tonumber(ARGV[1])
local refill_per_second = tonumber(ARGV[2])
local ttl = tonumber(ARGV[3])
local cost = tonumber(ARGV[4])
local redis_time = redis.call('TIME')
local now_ms = (tonumber(redis_time[1]) * 1000)
    + math.floor(tonumber(redis_time[2]) / 1000)

local tokens = tonumber(redis.call('HGET', KEYS[1], 'tokens')) or capacity
local last_ms = tonumber(redis.call('HGET', KEYS[1], 'last_ms')) or now_ms
local elapsed_ms = math.max(now_ms - last_ms, 0)
tokens = math.min(tokens + (elapsed_ms * refill_per_second) / 1000, capacity)

local allowed = 0
local retry_after = 0
if cost <= 0 then
  -- refund path: never fails, never exceeds capacity
  allowed = 1
  tokens = math.min(tokens - cost, capacity)
elseif tokens >= cost then
  allowed = 1
  tokens = tokens - cost
else
  retry_after = math.ceil((cost - tokens) / refill_per_second)
end

redis.call('HSET', KEYS[1], 'tokens', tokens, 'last_ms', now_ms)
redis.call('EXPIRE', KEYS[1], ttl)

local reset = math.ceil((capacity - tokens) / refill_per_second)
return {allowed, math.floor(tokens), retry_after, reset}
"""


@dataclass(frozen=True)
class RateLimitResult:
    """Bucket state after an allowed request, for RateLimit-* headers."""

    limit: int
    remaining: int
    reset: int

    def headers(self) -> dict[str, str]:
        return {
            "RateLimit-Limit": str(self.limit),
            "RateLimit-Remaining": str(self.remaining),
            "RateLimit-Reset": str(self.reset),
        }


def build_trusted_proxy_set(trusted_proxy_ips: Iterable[str]) -> frozenset[str]:
    """Normalise trusted proxy addresses once, at startup.

    Doing this per request would add work to the path that exists to reject
    floods as cheaply as possible.
    """
    return frozenset(
        str(ipaddress.ip_address(address)) for address in trusted_proxy_ips
    )


# other service call this function
async def enforce_pre_auth_rate_limit(
    request: Request, redis: Redis, trusted_proxies: frozenset[str]
) -> RateLimitResult:
    return await check_pre_auth_rate_limit(
        redis, get_trusted_proxy_ip(request, trusted_proxies)
    )


async def check_pre_auth_rate_limit(redis: Redis, ip: str) -> RateLimitResult:
    try:
        allowed, remaining, retry_after, reset = await redis.eval(
            _BUCKET_LUA,
            1,  # redis key amount
            f"rl:ip:{ip}",  # redis key
            CAPACITY,  # ARGV[1]
            REFILL_PER_SECOND,
            BUCKET_TTL_SECONDS,
            1,  # cost
        )
    except RedisError as exc:
        # fail closed: the endpoint downstream costs real money, so letting
        # traffic through unchecked is worse than a temporary outage
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
                "RateLimit-Reset": str(int(reset)),
                "Retry-After": str(retry_seconds),
            },
        )

    return RateLimitResult(limit=CAPACITY, remaining=int(remaining), reset=int(reset))


async def refund_pre_auth_token(redis: Redis, ip: str) -> None:
    """Return the token spent by a request that turned out to be authentic.

    The IP bucket then counts only failures, so a user who misconfigures a key
    and retries is not locked out once they fix it. A failed refund is ignored:
    the request already succeeded, and the token refills on its own. This path
    deliberately does not fail closed.
    """
    try:
        await redis.eval(
            _BUCKET_LUA,
            1,
            f"rl:ip:{ip}",
            CAPACITY,
            REFILL_PER_SECOND,
            BUCKET_TTL_SECONDS,
            -1,  # cost
        )
    except RedisError:
        pass


def get_trusted_proxy_ip(request: Request, trusted_proxies: frozenset[str]) -> str:
    # check proxy IP -> nginx
    proxy_ip = request.client.host if request.client else None
    if proxy_ip not in trusted_proxies:
        raise _bad_client_ip()

    # X-Real-IP is set by nginx with proxy_set_header, which overwrites
    # whatever the client sent. X-Forwarded-For is appended to instead, so its
    # leftmost values are attacker-controlled and its rightmost value is the
    # real client only when exactly one proxy sits in front of us. Requiring
    # X-Real-IP keeps the trusted path unambiguous.
    client_ip = request.headers.get("X-Real-IP")
    if client_ip is None:
        raise _bad_client_ip()

    try:
        return str(ipaddress.ip_address(client_ip.strip()))
    except ValueError as exc:
        raise _bad_client_ip() from exc


def _bad_client_ip() -> HTTPException:
    """One message for every client-IP failure.

    Distinct messages would tell a caller which stage of the pipeline they
    reached, which helps nobody except someone probing it.
    """
    return HTTPException(
        status_code=400,
        detail="Request must arrive through a trusted proxy.",
    )
