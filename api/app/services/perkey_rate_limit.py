"""Per-API-key rate limiting: one request bucket and one token bucket, one shot."""

from dataclasses import dataclass
from typing import Literal

from fastapi import HTTPException
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.constants.perkey_rate_limit import (
    MAX_INPUT_TOKENS,
    RATE_LIMIT_CAPACITY,
    RATE_LIMIT_REFILL_PER_MIN,
    RATE_LIMIT_TTL_S,
    TOKEN_RATE_LIMIT_CAPACITY,
    TOKEN_RATE_LIMIT_REFILL_PER_MIN,
)

LimitType = Literal["request", "token"]

_REQUEST_REFILL_PER_SECOND = RATE_LIMIT_REFILL_PER_MIN / 60
_TOKEN_REFILL_PER_SECOND = TOKEN_RATE_LIMIT_REFILL_PER_MIN / 60

# KEYS[1]=request bucket  KEYS[2]=token bucket
# ARGV: req_capacity, req_refill_per_second, tok_capacity, tok_refill_per_second,
#       ttl, est_tokens
# Both buckets are refilled and checked before either is debited, so a denial
# leaves no state behind. Redis TIME is the only clock: the app's own clock
# drifts per worker and would let two workers disagree about the same bucket.
_PERKEY_LUA = """
local req_capacity = tonumber(ARGV[1])
local req_refill = tonumber(ARGV[2])
local tok_capacity = tonumber(ARGV[3])
local tok_refill = tonumber(ARGV[4])
local ttl = tonumber(ARGV[5])
local est_tokens = tonumber(ARGV[6])

local redis_time = redis.call('TIME')
local now_ms = (tonumber(redis_time[1]) * 1000)
    + math.floor(tonumber(redis_time[2]) / 1000)

local function peek(key, capacity, refill)
  local state = redis.call('HMGET', key, 'tokens', 'last_ms')
  local tokens = tonumber(state[1]) or capacity
  local last_ms = tonumber(state[2]) or now_ms
  local elapsed_ms = math.max(now_ms - last_ms, 0)
  return math.min(tokens + (elapsed_ms * refill) / 1000, capacity)
end

local function deny(capacity, tokens, refill, cost, limit_type)
  return {
    0,
    limit_type,
    capacity,
    math.floor(tokens),
    math.ceil((capacity - tokens) / refill),
    math.ceil((cost - tokens) / refill),
  }
end

local req_tokens = peek(KEYS[1], req_capacity, req_refill)
local tok_tokens = peek(KEYS[2], tok_capacity, tok_refill)

if req_tokens < 1 then
  return deny(req_capacity, req_tokens, req_refill, 1, 'request')
end
if tok_tokens < est_tokens then
  return deny(tok_capacity, tok_tokens, tok_refill, est_tokens, 'token')
end

req_tokens = req_tokens - 1
tok_tokens = tok_tokens - est_tokens
redis.call('HSET', KEYS[1], 'tokens', req_tokens, 'last_ms', now_ms)
redis.call('EXPIRE', KEYS[1], ttl)
redis.call('HSET', KEYS[2], 'tokens', tok_tokens, 'last_ms', now_ms)
redis.call('EXPIRE', KEYS[2], ttl)

return {
  1,
  'request',
  req_capacity,
  math.floor(req_tokens),
  math.ceil((req_capacity - req_tokens) / req_refill),
  0,
}
"""


@dataclass(frozen=True)
class PerKeyRateLimitResult:
    """State of the bucket that decided the outcome, for RateLimit-* headers."""

    limit: int
    remaining: int
    reset: int
    limit_type: LimitType

    def headers(self) -> dict[str, str]:
        return {
            "RateLimit-Limit": str(self.limit),
            "RateLimit-Remaining": str(self.remaining),
            "RateLimit-Reset": str(self.reset),
        }


async def perkey_rate_limit(
    redis: Redis, user_id: int, est_tokens: int
) -> PerKeyRateLimitResult:
    """Charge one request and `est_tokens` against the key's buckets, atomically.

    `user_id` must come from the authentication record, never from the request:
    the bucket key is the only thing separating one caller's quota from another's.
    """
    _require_positive_int(user_id, "user_id")
    _require_positive_int(est_tokens, "est_tokens")

    if est_tokens > MAX_INPUT_TOKENS:
        raise HTTPException(
            status_code=413,
            detail=f"Request exceeds the {MAX_INPUT_TOKENS} token limit.",
        )

    try:
        allowed, limit_type, limit, remaining, reset, retry_after = await redis.eval(
            _PERKEY_LUA,
            2,
            f"rl:key:{user_id}",
            f"rl:tok:{user_id}",
            RATE_LIMIT_CAPACITY,
            _REQUEST_REFILL_PER_SECOND,
            TOKEN_RATE_LIMIT_CAPACITY,
            _TOKEN_REFILL_PER_SECOND,
            RATE_LIMIT_TTL_S,
            est_tokens,
        )
    except RedisError as exc:
        # fail closed, same reasoning as the pre-auth bucket: the endpoint
        # behind this costs real money per call
        raise HTTPException(
            status_code=503,
            detail="Rate limiting is temporarily unavailable.",
        ) from exc

    result = PerKeyRateLimitResult(
        limit=int(limit),
        remaining=int(remaining),
        reset=int(reset),
        limit_type=_as_limit_type(limit_type),
    )

    if int(allowed) == 0:
        retry_seconds = max(int(retry_after), 1)
        raise HTTPException(
            status_code=429,
            detail=f"Too many requests. Retry in {retry_seconds}s.",
            headers={**result.headers(), "Retry-After": str(retry_seconds)},
        )

    return result


def _require_positive_int(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def _as_limit_type(raw: object) -> LimitType:
    value = raw.decode() if isinstance(raw, bytes) else str(raw)
    return "token" if value == "token" else "request"
