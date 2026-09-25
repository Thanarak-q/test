"""quota_reserve / reconcile / release against a real Redis."""

import pytest

from app.config import settings
from app.envelope import AppError
from app.services.quota import (
    Reservation,
    quota_key,
    quota_reconcile,
    quota_release,
    quota_reserve,
    quota_schema_problems,
    read_quota,
    reservation_key,
)

USER = 42


async def reserve(redis, request_id="req-1", est=100):
    return await quota_reserve(
        redis, user_id=USER, request_id=request_id, est_tokens=est
    )


async def test_reserve_holds_the_estimate(redis):
    await redis.hset(quota_key(USER), mapping={"limit": 1000, "used": 0})

    reservation = await reserve(redis, est=300)

    assert reservation.est_tokens == 300
    assert await redis.zrange(reservation_key(USER), 0, -1) == ["req-1:300"]
    assert 0 < await redis.ttl(reservation_key(USER)) <= 600


async def test_in_flight_reservations_count_against_the_limit(redis):
    await redis.hset(quota_key(USER), mapping={"limit": 1000, "used": 500})
    await reserve(redis, "a", 300)

    with pytest.raises(AppError) as exc_info:
        await reserve(redis, "b", 201)  # 500 used + 300 held + 201 > 1000

    assert exc_info.value.status_code == 422
    assert exc_info.value.code == "llm_quota_exceeded"
    # Says only that it failed, never what is left.
    assert not any(ch.isdigit() for ch in exc_info.value.message)
    await reserve(redis, "c", 200)  # exactly at the limit is fine


async def test_expired_reservations_stop_counting(redis):
    await redis.hset(quota_key(USER), mapping={"limit": 1000, "used": 0})
    await redis.zadd(reservation_key(USER), {"stale:900": 1.0})  # 1970

    await reserve(redis, "fresh", 900)

    assert await redis.zrange(reservation_key(USER), 0, -1) == ["fresh:900"]


async def test_missing_limit_uses_the_default_and_missing_used_is_zero(redis):
    await reserve(redis, est=settings.llm_token_quota)

    with pytest.raises(AppError):
        await reserve(redis, "again", 1)


@pytest.mark.parametrize("field", ["limit", "used"])
@pytest.mark.parametrize("value", ["-5", "1.5", "lots", ""])
async def test_malformed_main_app_values_fail_closed(redis, field, value):
    await redis.hset(quota_key(USER), mapping={"limit": 1000, "used": 0})
    await redis.hset(quota_key(USER), field, value)

    with pytest.raises(AppError) as exc_info:
        await reserve(redis)

    assert exc_info.value.status_code == 503
    assert exc_info.value.code == "llm_quota_unavailable"
    assert await redis.exists(reservation_key(USER)) == 0


async def test_redis_down_fails_closed(unreachable_redis):
    with pytest.raises(AppError) as exc_info:
        await reserve(unreachable_redis)

    assert exc_info.value.status_code == 503


async def test_reconcile_charges_actual_and_drops_the_reservation(redis):
    await redis.hset(quota_key(USER), mapping={"limit": 1000, "used": 10})
    reservation = await reserve(redis, est=300)

    assert await quota_reconcile(redis, reservation, 120) is True

    assert await redis.hget(quota_key(USER), "used") == "130"
    assert await redis.zcard(reservation_key(USER)) == 0


async def test_reconcile_of_an_expired_reservation_charges_nothing(redis):
    await redis.hset(quota_key(USER), mapping={"limit": 1000, "used": 10})
    reservation = await reserve(redis, est=300)
    await redis.delete(reservation_key(USER))

    assert await quota_reconcile(redis, reservation, 120) is False
    assert await redis.hget(quota_key(USER), "used") == "10"


async def test_release_is_idempotent_and_charges_nothing(redis):
    await redis.hset(quota_key(USER), mapping={"limit": 1000, "used": 10})
    reservation = await reserve(redis, est=300)
    await reserve(redis, "other", 50)

    await quota_release(redis, reservation)
    await quota_release(redis, reservation)

    assert await redis.zrange(reservation_key(USER), 0, -1) == ["other:50"]
    assert await redis.hget(quota_key(USER), "used") == "10"


def test_a_reservation_cannot_be_forged():
    with pytest.raises(TypeError):
        Reservation(user_id=1, request_id="r", est_tokens=1)


async def test_read_quota_and_schema_check(redis):
    assert await quota_schema_problems(redis, USER) == [f"quota:{USER} does not exist"]
    await redis.hset(quota_key(USER), mapping={"limit": 1000, "used": "x"})

    problems = await quota_schema_problems(redis, USER)
    with pytest.raises(AppError):
        await read_quota(redis, USER)

    assert problems == [f"quota:{USER} `used` is not an integer: 'x'"]
    await redis.hset(quota_key(USER), "used", 7)
    state = await read_quota(redis, USER)
    assert (state.limit, state.used) == (1000, 7)
    assert await quota_schema_problems(redis, USER) == []
