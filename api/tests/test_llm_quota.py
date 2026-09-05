"""The reservation is the whole point of the quota rewrite — check it holds under
concurrency, refunds on failure, and reconciles to the provider's real count."""

import asyncio

import pytest

from app.envelope import AppError
from app.services import llm_quota
from app.services.llm_chat import estimate_tokens


class FakeRedis:
    """Counter subset of redis-py. Single-threaded asyncio makes these atomic."""

    def __init__(self) -> None:
        self.store: dict[str, int] = {}

    async def set(self, key: str, value: int, nx: bool = False) -> bool:
        if nx and key in self.store:
            return False
        self.store[key] = int(value)
        return True

    async def incrby(self, key: str, amount: int) -> int:
        self.store[key] = self.store.get(key, 0) + amount
        return self.store[key]

    async def decrby(self, key: str, amount: int) -> int:
        return await self.incrby(key, -amount)


class FakeQuotaRow:
    def __init__(self, token_limit: int, token_used: int) -> None:
        self.token_limit = token_limit
        self.token_used = token_used


@pytest.fixture
def quota_db(monkeypatch):
    state = {"limit": 5_000, "used": 0, "applied": []}

    async def get_quota(_session, _user_id):
        return FakeQuotaRow(state["limit"], state["used"])

    async def add_token_usage(_session, user_id, tokens, token_limit):
        state["applied"].append((user_id, tokens, token_limit))
        state["used"] += tokens

    monkeypatch.setattr(llm_quota.llm_repo, "get_quota", get_quota)
    monkeypatch.setattr(llm_quota.llm_repo, "add_token_usage", add_token_usage)
    return state


async def test_reserve_blocks_concurrent_requests_from_exceeding_the_limit(quota_db):
    redis = FakeRedis()

    async def try_reserve():
        try:
            return await llm_quota.reserve(redis, None, 1, 2_000)
        except AppError:
            return None

    results = await asyncio.gather(*(try_reserve() for _ in range(5)))

    assert sum(r is not None for r in results) == 2
    assert redis.store["llm:quota:1:spent"] == 4_000


async def test_release_returns_the_reservation(quota_db):
    redis = FakeRedis()
    reservation = await llm_quota.reserve(redis, None, 1, 2_000)

    await llm_quota.release(redis, reservation)

    assert redis.store["llm:quota:1:spent"] == 0


async def test_settle_replaces_the_estimate_with_the_real_count(quota_db):
    redis = FakeRedis()
    reservation = await llm_quota.reserve(redis, None, 1, 2_000)

    await llm_quota.settle(redis, None, reservation, 150)

    assert redis.store["llm:quota:1:spent"] == 150
    assert quota_db["applied"] == [(1, 150, 5_000)]


async def test_counter_reseeds_from_the_db_when_redis_lost_the_key(quota_db):
    quota_db["used"] = 4_500
    redis = FakeRedis()

    with pytest.raises(AppError):
        await llm_quota.reserve(redis, None, 1, 1_000)

    assert redis.store["llm:quota:1:spent"] == 4_500


def test_estimate_covers_prompt_plus_reserved_output():
    messages = [{"role": "user", "content": "x" * 400}]

    assert estimate_tokens(messages, max_tokens=200) == 100 + 4 + 200
