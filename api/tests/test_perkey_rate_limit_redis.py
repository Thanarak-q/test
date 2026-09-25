"""The per-key Lua script against a real Redis.

The stub tests pin the Python side; only a real server proves the script
itself returns what the Python side unpacks. Uses the compose Redis
(`docker compose up redis`); see conftest for when it skips.
"""

import pytest

from app.constants.perkey_rate_limit import (
    RATE_LIMIT_CAPACITY,
    TOKEN_RATE_LIMIT_CAPACITY,
)
from app.envelope import AppError
from app.services.perkey_rate_limit import perkey_rate_limit

USER_ID = 424242


async def test_allowed_request_reports_each_bucket_separately(redis):
    result = await perkey_rate_limit(redis, USER_ID, 500)

    assert result.requests.limit == RATE_LIMIT_CAPACITY
    assert result.requests.remaining == RATE_LIMIT_CAPACITY - 1
    assert result.tokens.limit == TOKEN_RATE_LIMIT_CAPACITY
    assert result.tokens.remaining == TOKEN_RATE_LIMIT_CAPACITY - 500
    assert await redis.exists(f"rl:req:{USER_ID}", f"rl:tok:{USER_ID}") == 2
    assert await redis.exists(f"rl:key:{USER_ID}") == 0


async def test_token_denial_debits_neither_bucket(redis):
    await perkey_rate_limit(redis, USER_ID, 8_000)
    await perkey_rate_limit(redis, USER_ID, 8_000)

    with pytest.raises(AppError) as exc_info:
        await perkey_rate_limit(redis, USER_ID, 8_000)

    exc = exc_info.value
    assert exc.code == "rate_limit_exceeded_tokens"
    assert int(exc.headers["RateLimit-Remaining"]) == RATE_LIMIT_CAPACITY - 2
    assert int(exc.headers["Retry-After"]) >= 1


async def test_request_denial_names_the_request_bucket(redis):
    for _ in range(RATE_LIMIT_CAPACITY):
        await perkey_rate_limit(redis, USER_ID, 1)

    with pytest.raises(AppError) as exc_info:
        await perkey_rate_limit(redis, USER_ID, 1)

    assert exc_info.value.code == "rate_limit_exceeded_requests"
    assert exc_info.value.headers["RateLimit-Remaining"] == "0"
