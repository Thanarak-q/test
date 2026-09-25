import pytest
from fastapi import HTTPException
from redis.exceptions import RedisError

from app.constants.perkey_rate_limit import (
    MAX_INPUT_TOKENS,
    RATE_LIMIT_CAPACITY,
    TOKEN_RATE_LIMIT_CAPACITY,
)
from app.envelope import AppError
from app.services.perkey_rate_limit import (
    check_token_bucket_fits_largest_request,
    perkey_rate_limit,
)

# allowed, limit_type, req_remaining, req_reset, tok_remaining, tok_reset, retry
ALLOWED_REPLY = [1, "", 9, 3, 19_880, 1, 0]


class StubRedis:
    """Records the eval call and replays a canned script reply.

    The Lua itself is only exercised against a real Redis; re-implementing it
    here would test the copy, not the script that ships.
    """

    def __init__(self, reply=None, error=False):
        self.reply = reply or ALLOWED_REPLY
        self.error = error
        self.calls = []

    async def eval(self, script, numkeys, *args):
        if self.error:
            raise RedisError("down")
        self.calls.append((numkeys, list(args)))
        return self.reply


async def test_allows_and_charges_both_buckets():
    redis = StubRedis()

    result = await perkey_rate_limit(redis, 7, 120)

    numkeys, args = redis.calls[0]
    assert numkeys == 2
    assert args[0:2] == ["rl:req:7", "rl:tok:7"]
    assert args[-1] == 120  # cost passed through unchanged
    assert result.headers() == {
        "RateLimit-Limit": str(RATE_LIMIT_CAPACITY),
        "RateLimit-Remaining": "9",
        "RateLimit-Reset": "3",
        "X-RateLimit-Tokens-Limit": str(TOKEN_RATE_LIMIT_CAPACITY),
        "X-RateLimit-Tokens-Remaining": "19880",
        "X-RateLimit-Tokens-Reset": "1",
    }


async def test_denied_request_bucket_is_429_with_both_header_sets():
    redis = StubRedis([0, "requests", 0, 12, 20_000, 0, 4])

    with pytest.raises(AppError) as exc_info:
        await perkey_rate_limit(redis, 7, 120)

    exc = exc_info.value
    assert exc.status_code == 429
    assert exc.code == "rate_limit_exceeded_requests"
    assert exc.headers == {
        "RateLimit-Limit": str(RATE_LIMIT_CAPACITY),
        "RateLimit-Remaining": "0",
        "RateLimit-Reset": "12",
        "X-RateLimit-Tokens-Limit": str(TOKEN_RATE_LIMIT_CAPACITY),
        "X-RateLimit-Tokens-Remaining": "20000",
        "X-RateLimit-Tokens-Reset": "0",
        "Retry-After": "4",
    }


async def test_denied_token_bucket_keeps_request_headers_for_requests():
    redis = StubRedis([0, "tokens", 8, 6, 30, 60, 9])

    with pytest.raises(AppError) as exc_info:
        await perkey_rate_limit(redis, 7, 120)

    exc = exc_info.value
    assert exc.code == "rate_limit_exceeded_tokens"
    # token state never leaks into the request headers
    assert exc.headers["RateLimit-Limit"] == str(RATE_LIMIT_CAPACITY)
    assert exc.headers["RateLimit-Remaining"] == "8"
    assert exc.headers["X-RateLimit-Tokens-Remaining"] == "30"
    assert exc.headers["Retry-After"] == "9"


async def test_retry_after_never_drops_below_one_second():
    redis = StubRedis([0, "requests", 0, 1, 20_000, 0, 0])

    with pytest.raises(AppError) as exc_info:
        await perkey_rate_limit(redis, 7, 1)

    assert exc_info.value.headers["Retry-After"] == "1"


def test_shipped_limits_fit_the_largest_request():
    check_token_bucket_fits_largest_request()


def test_startup_check_rejects_request_larger_than_bucket():
    with pytest.raises(RuntimeError):
        check_token_bucket_fits_largest_request(max_cost=20_001, capacity=20_000)


async def test_oversized_estimate_is_413_before_redis():
    redis = StubRedis()

    with pytest.raises(HTTPException) as exc_info:
        await perkey_rate_limit(redis, 7, MAX_INPUT_TOKENS + 1)

    assert exc_info.value.status_code == 413
    assert redis.calls == []


@pytest.mark.parametrize("user_id", [0, -1, True, "7", 1.0])
async def test_rejects_bad_user_id_before_redis(user_id):
    redis = StubRedis()

    with pytest.raises(ValueError):
        await perkey_rate_limit(redis, user_id, 10)

    assert redis.calls == []


@pytest.mark.parametrize("est_tokens", [0, -1, True, "10", 1.0])
async def test_rejects_bad_est_tokens_before_redis(est_tokens):
    redis = StubRedis()

    with pytest.raises(ValueError):
        await perkey_rate_limit(redis, 7, est_tokens)

    assert redis.calls == []


async def test_redis_failure_fails_closed_with_503():
    with pytest.raises(HTTPException) as exc_info:
        await perkey_rate_limit(StubRedis(error=True), 7, 10)

    assert exc_info.value.status_code == 503
