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
from app.envelope import AppError

LimitType = Literal["requests", "tokens"]

_REQUEST_REFILL_PER_SECOND = RATE_LIMIT_REFILL_PER_MIN / 60
_TOKEN_REFILL_PER_SECOND = TOKEN_RATE_LIMIT_REFILL_PER_MIN / 60

# KEYS[1]=request bucket  KEYS[2]=token bucket
# ARGV: req_capacity, req_refill_per_second, tok_capacity, tok_refill_per_second,
#       ttl, est_tokens
# Both buckets are refilled and checked before either is debited, so a denial
# leaves no state behind. Redis TIME is the only clock: the app's own clock
# drifts per worker and would let two workers disagree about the same bucket.
# Returns: allowed, limit_type, req_remaining, req_reset, tok_remaining,
#          tok_reset, retry_after. Both buckets are always reported so each
#          gets its own header set.
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

local function reset_s(capacity, tokens, refill)
  return math.ceil((capacity - tokens) / refill)
end

local function reply(allowed, limit_type, req_tokens, tok_tokens, retry_after)
  return {
    allowed,
    limit_type,
    math.floor(req_tokens),
    reset_s(req_capacity, req_tokens, req_refill),
    math.floor(tok_tokens),
    reset_s(tok_capacity, tok_tokens, tok_refill),
    retry_after,
  }
end

local req_tokens = peek(KEYS[1], req_capacity, req_refill)
local tok_tokens = peek(KEYS[2], tok_capacity, tok_refill)

if req_tokens < 1 then
  return reply(0, 'requests', req_tokens, tok_tokens,
    math.ceil((1 - req_tokens) / req_refill))
end
if tok_tokens < est_tokens then
  return reply(0, 'tokens', req_tokens, tok_tokens,
    math.ceil((est_tokens - tok_tokens) / tok_refill))
end

req_tokens = req_tokens - 1
tok_tokens = tok_tokens - est_tokens
redis.call('HSET', KEYS[1], 'tokens', req_tokens, 'last_ms', now_ms)
redis.call('EXPIRE', KEYS[1], ttl)
redis.call('HSET', KEYS[2], 'tokens', tok_tokens, 'last_ms', now_ms)
redis.call('EXPIRE', KEYS[2], ttl)

return reply(1, '', req_tokens, tok_tokens, 0)
"""


@dataclass(frozen=True)
class BucketState:
    limit: int
    remaining: int
    reset: int


@dataclass(frozen=True)
class PerKeyRateLimitResult:
    """State of both buckets after the charge, for the rate limit headers."""

    requests: BucketState
    tokens: BucketState

    def headers(self) -> dict[str, str]:
        # RateLimit-* describes the request bucket only. Reporting token state
        # under the same names would tell a client it has 19,000 "requests"
        # left, and it would back off (or not) on the wrong number.
        return {
            "RateLimit-Limit": str(self.requests.limit),
            "RateLimit-Remaining": str(self.requests.remaining),
            "RateLimit-Reset": str(self.requests.reset),
            "X-RateLimit-Tokens-Limit": str(self.tokens.limit),
            "X-RateLimit-Tokens-Remaining": str(self.tokens.remaining),
            "X-RateLimit-Tokens-Reset": str(self.tokens.reset),
        }


def check_token_bucket_fits_largest_request(
    max_cost: int = MAX_INPUT_TOKENS, capacity: int = TOKEN_RATE_LIMIT_CAPACITY
) -> None:
    """Refuse to start if one allowed request could cost more than a full bucket.

    Such a request would pass the 413 check and then be denied with 429
    forever, since the bucket can never hold enough to pay for it. Raised
    rather than asserted so `python -O` cannot strip it.
    """
    if max_cost > capacity:
        raise RuntimeError(
            f"MAX_INPUT_TOKENS ({max_cost}) exceeds TOKEN_RATE_LIMIT_CAPACITY "
            f"({capacity}); such a request would be rate limited forever."
        )


def request_bucket_key(user_id: int) -> str:
    return f"rl:req:{user_id}"


def token_bucket_key(user_id: int) -> str:
    return f"rl:tok:{user_id}"


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
        (
            allowed,
            limit_type,
            req_remaining,
            req_reset,
            tok_remaining,
            tok_reset,
            retry_after,
        ) = await redis.eval(
            _PERKEY_LUA,
            2,
            request_bucket_key(user_id),
            token_bucket_key(user_id),
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
        requests=BucketState(
            limit=RATE_LIMIT_CAPACITY,
            remaining=int(req_remaining),
            reset=int(req_reset),
        ),
        tokens=BucketState(
            limit=TOKEN_RATE_LIMIT_CAPACITY,
            remaining=int(tok_remaining),
            reset=int(tok_reset),
        ),
    )

    if int(allowed) == 0:
        denied_by = _as_limit_type(limit_type)
        retry_seconds = max(int(retry_after), 1)
        raise AppError(
            code=f"rate_limit_exceeded_{denied_by}",
            message=f"Too many {denied_by}. Retry in {retry_seconds}s.",
            status_code=429,
            headers={**result.headers(), "Retry-After": str(retry_seconds)},
        )

    return result


def _require_positive_int(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def _as_limit_type(raw: object) -> LimitType:
    value = raw.decode() if isinstance(raw, bytes) else str(raw)
    return "tokens" if value == "tokens" else "requests"
