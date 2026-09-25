"""IP rate limiting that runs before API key validation."""

from dataclasses import dataclass

from fastapi import HTTPException
from redis.asyncio import Redis
from redis.exceptions import RedisError

CAPACITY = 60  # capacity of token bucket; shared IPs may serve many devices
REFILL_PER_SECOND = 1.0  # refill token in token bucket
BUCKET_TTL_SECONDS = 300  # no incoming request from that ip for 5 mins -> delete bucket

RATE_LIMIT_UNAVAILABLE_MESSAGE = "Rate limiting is temporarily unavailable."

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


def bucket_key(ip: str) -> str:
    return f"rl:ip:{ip}"


async def check_pre_auth_rate_limit(redis: Redis, ip: str) -> RateLimitResult:
    """Spend one token for this IP, or reject the request.

    The IP is expected to come from get_client_ip, which only returns a value
    for a request that arrived through a trusted proxy.
    """
    try:
        allowed, remaining, retry_after, reset = await redis.eval(
            _BUCKET_LUA,
            1,  # redis key amount
            bucket_key(ip),
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
            detail=RATE_LIMIT_UNAVAILABLE_MESSAGE,
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
    and retries is not locked out once they fix it.

    Call this at most once per request: the bucket has no record of which
    request spent which token, so repeated refunds would hand back more than
    was taken.

    A failed refund is ignored. The request already succeeded, the token
    refills on its own, and this path deliberately does not fail closed.
    """
    try:
        await redis.eval(
            _BUCKET_LUA,
            1,
            bucket_key(ip),
            CAPACITY,
            REFILL_PER_SECOND,
            BUCKET_TTL_SECONDS,
            -1,  # cost
        )
    except RedisError:
        pass
