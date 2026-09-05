"""Token bucket in Redis. One Lua script so concurrent requests cannot both pass."""

import time

from redis.asyncio import Redis

from app.constants.llm import (
    RATE_LIMIT_CAPACITY,
    RATE_LIMIT_REFILL_PER_MIN,
    RATE_LIMIT_TTL_S,
)
from app.envelope import AppError

# KEYS[1]=bucket  ARGV: capacity, refill_per_min, now_ms, ttl -> {allowed, retry_s}
_BUCKET_LUA = """
local capacity = tonumber(ARGV[1])
local refill = tonumber(ARGV[2])
local now_ms = tonumber(ARGV[3])
local ttl = tonumber(ARGV[4])

local tokens = tonumber(redis.call('HGET', KEYS[1], 'tokens')) or capacity
local last = tonumber(redis.call('HGET', KEYS[1], 'last_ms')) or now_ms

local elapsed = math.max(now_ms - last, 0)
tokens = math.min(tokens + (elapsed * refill) / 60000.0, capacity)

local allowed, retry = 0, 0
if tokens >= 1 then
  allowed, tokens = 1, tokens - 1
else
  retry = math.ceil(((1 - tokens) * 60.0) / refill)
end

redis.call('HSET', KEYS[1], 'tokens', tokens, 'last_ms', now_ms)
redis.call('EXPIRE', KEYS[1], ttl)
return {allowed, retry}
"""


async def check_rate_limit(redis: Redis, identity: str) -> None:
    allowed, retry_after = await redis.eval(
        _BUCKET_LUA,
        1,
        f"llm:ratelimit:{identity}",
        RATE_LIMIT_CAPACITY,
        RATE_LIMIT_REFILL_PER_MIN,
        int(time.time() * 1000),
        RATE_LIMIT_TTL_S,
    )
    if not int(allowed):
        raise AppError(
            "llm_rate_limited",
            f"Too many requests. Retry in {int(retry_after)}s.",
            status_code=429,
        )
