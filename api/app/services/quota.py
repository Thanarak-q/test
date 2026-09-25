"""Token quota: reserve before the provider call, reconcile or release after.

The quota itself belongs to the main application: Redis hash
`quota:{user_id}` with integer fields `limit` and `used`. We never add
fields to it. Our in-flight reservations live beside it in the sorted set
`api:quota:resv:{user_id}`, one member "{request_id}:{est}" per request,
scored by reservation time. The reserved total is computed live from the
members that have not expired, so a crashed worker leaves nothing behind
for longer than the reservation window.

Cross-system atomicity: HINCRBY is atomic on our side, but the main
application must also update `used` with HINCRBY. If it ever uses SET, our
increments are overwritten (open question 3 in CLAUDE_CODE_BRIEF.md).

Every Redis failure here is a 503: the provider behind this costs real
money, so letting a request through unchecked is worse than refusing it.
"""

import logging
import re
from dataclasses import dataclass, field

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config import settings
from app.constants.llm import (
    QUOTA_RESERVATION_KEY_TTL_SECONDS,
    QUOTA_RESERVATION_TTL_SECONDS,
)
from app.envelope import AppError

logger = logging.getLogger(__name__)

# ASCII digits only, the same test as the Lua scripts' `^%d+$`.
_NON_NEGATIVE_INT = re.compile(r"[0-9]+")

_PROOF = object()


def reservation_key(user_id: int) -> str:
    return f"api:quota:resv:{user_id}"


def quota_key(user_id: int) -> str:
    return f"quota:{user_id}"


@dataclass(frozen=True)
class Reservation:
    """Proof that quota_reserve accepted this request's estimate.

    Only this module can build one, so proxy_to_llm cannot be reached by a
    path that skipped the quota check.
    """

    user_id: int
    request_id: str
    est_tokens: int
    _proof: object = field(repr=False, compare=False, default=None)

    def __post_init__(self) -> None:
        if self._proof is not _PROOF:
            raise TypeError("Reservation is issued by quota_reserve only")


@dataclass(frozen=True)
class QuotaState:
    limit: int
    used: int


# KEYS[1]=api:quota:resv:{user}  KEYS[2]=quota:{user}
# ARGV: request_id, est, default_limit, window_seconds, key_ttl
# Returns {status, detail}: 1 reserved, 0 over quota, -1 malformed (detail
# names the field). Redis TIME is the only clock.
_RESERVE_LUA = """
local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - tonumber(ARGV[4]))

local reserved = 0
for _, member in ipairs(redis.call('ZRANGE', KEYS[1], 0, -1)) do
  local est = tonumber(string.match(member, ':(%d+)$'))
  if est then reserved = reserved + est end
end

local limit_raw = redis.call('HGET', KEYS[2], 'limit')
local used_raw = redis.call('HGET', KEYS[2], 'used')
if limit_raw and not string.match(limit_raw, '^%d+$') then return {-1, 'limit'} end
if used_raw and not string.match(used_raw, '^%d+$') then return {-1, 'used'} end
local limit = tonumber(limit_raw or ARGV[3])
local used = tonumber(used_raw or '0')
local est = tonumber(ARGV[2])

if used + reserved + est > limit then return {0, ''} end

redis.call('ZADD', KEYS[1], now, ARGV[1] .. ':' .. ARGV[2])
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[5]))
return {1, ''}
"""

# KEYS[1]=api:quota:resv:{user}  KEYS[2]=quota:{user}  ARGV: request_id, actual
# Returns 1 when the reservation was found and settled, 0 when it had expired.
_RECONCILE_LUA = """
local prefix = ARGV[1] .. ':'
for _, member in ipairs(redis.call('ZRANGE', KEYS[1], 0, -1)) do
  if string.sub(member, 1, #prefix) == prefix then
    redis.call('ZREM', KEYS[1], member)
    redis.call('HINCRBY', KEYS[2], 'used', tonumber(ARGV[2]))
    return 1
  end
end
return 0
"""

# KEYS[1]=api:quota:resv:{user}  ARGV: request_id. Idempotent.
_RELEASE_LUA = """
local prefix = ARGV[1] .. ':'
for _, member in ipairs(redis.call('ZRANGE', KEYS[1], 0, -1)) do
  if string.sub(member, 1, #prefix) == prefix then
    redis.call('ZREM', KEYS[1], member)
    return 1
  end
end
return 0
"""


def _unavailable() -> AppError:
    return AppError(
        "llm_quota_unavailable",
        "Quota checks are temporarily unavailable. Try again shortly.",
        503,
    )


async def quota_reserve(
    redis: Redis, *, user_id: int, request_id: str, est_tokens: int
) -> Reservation:
    """Hold `est_tokens` against the user's quota, or 422.

    The 422 says only that the quota is used up — never how much is left.
    """
    try:
        status, detail = await redis.eval(
            _RESERVE_LUA,
            2,
            reservation_key(user_id),
            quota_key(user_id),
            request_id,
            est_tokens,
            settings.llm_token_quota,
            QUOTA_RESERVATION_TTL_SECONDS,
            QUOTA_RESERVATION_KEY_TTL_SECONDS,
        )
    except RedisError as exc:
        raise _unavailable() from exc

    status = int(status)
    if status == -1:
        # The main application's quota:{user_id} no longer holds integers:
        # its schema changed under us. Refuse rather than guess.
        logger.error(
            "ALERT quota:%s field %r is not a non-negative integer; "
            "main application quota schema may have changed",
            user_id,
            detail,
        )
        raise _unavailable()
    if status == 0:
        raise AppError(
            "llm_quota_exceeded",
            "Your token quota is used up. See the Usage page for details.",
            422,
        )
    return Reservation(
        user_id=user_id, request_id=request_id, est_tokens=est_tokens, _proof=_PROOF
    )


async def quota_reconcile(
    redis: Redis, reservation: Reservation, actual_tokens: int
) -> bool:
    """Replace the reservation with the validated actual. False if the
    reservation had already expired (logged; nothing is charged)."""
    settled = await redis.eval(
        _RECONCILE_LUA,
        2,
        reservation_key(reservation.user_id),
        quota_key(reservation.user_id),
        reservation.request_id,
        actual_tokens,
    )
    if not int(settled):
        logger.error(
            "quota reservation for request %s expired before settling; "
            "%d tokens not charged",
            reservation.request_id,
            actual_tokens,
        )
        return False
    return True


async def quota_release(redis: Redis, reservation: Reservation) -> None:
    """Drop the reservation without charging. Safe to call more than once."""
    await redis.eval(
        _RELEASE_LUA,
        1,
        reservation_key(reservation.user_id),
        reservation.request_id,
    )


def _parse_field(raw: str | None, name: str, default: int, user_id: int) -> int:
    if raw is None:
        return default
    if not _NON_NEGATIVE_INT.fullmatch(raw):
        logger.error("ALERT quota:%s field %r is not an integer", user_id, name)
        raise _unavailable()
    return int(raw)


async def read_quota(redis: Redis, user_id: int) -> QuotaState:
    """Limit and settled usage, for the dashboard. The public API never
    returns this: the quota is shared with the main app."""
    try:
        limit_raw, used_raw = await redis.hmget(quota_key(user_id), "limit", "used")
    except RedisError as exc:
        raise _unavailable() from exc
    return QuotaState(
        limit=_parse_field(limit_raw, "limit", settings.llm_token_quota, user_id),
        used=_parse_field(used_raw, "used", 0, user_id),
    )


async def quota_schema_problems(redis: Redis, user_id: int) -> list[str]:
    """What is wrong with quota:{user_id}, for the periodic health check.

    An empty list means the main application's hash still has the shape the
    reserve script relies on.
    """
    values = await redis.hgetall(quota_key(user_id))
    if not values:
        return [f"quota:{user_id} does not exist"]
    problems = []
    for name in ("limit", "used"):
        raw = values.get(name)
        if raw is None:
            problems.append(f"quota:{user_id} has no `{name}` field")
        elif not _NON_NEGATIVE_INT.fullmatch(raw):
            problems.append(f"quota:{user_id} `{name}` is not an integer: {raw!r}")
    return problems
