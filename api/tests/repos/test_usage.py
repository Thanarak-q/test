"""GET /v1/usage against real MySQL."""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import insert

from app.models import LlmUsageLog
from app.services import dashboard
from tests.repos.helpers import ALICE, BOB, as_user, seed_key

TODAY = date(2026, 9, 25)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(dashboard, "today", lambda zone=None: TODAY)


async def log(db, *, user_id, at, source="api", key_id=None, tokens=100):
    async with db.begin() as session:
        await session.execute(
            insert(LlmUsageLog).values(
                user_id=user_id,
                source=source,
                key_id=key_id,
                tokens=tokens,
                created_at=at,
            )
        )


async def usage(client, user_id=ALICE, **params):
    response = await client.get("/v1/usage", params=params, headers=as_user(user_id))
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def test_days_are_bangkok_days(client, db):
    key_id, _ = await seed_key(db, user_id=ALICE)
    # 18:30 UTC on the 24th is 01:30 on the 25th in Bangkok.
    await log(
        db, user_id=ALICE, key_id=key_id, at=datetime(2026, 9, 24, 18, 30, tzinfo=UTC)
    )
    await log(
        db, user_id=ALICE, key_id=key_id, at=datetime(2026, 9, 24, 16, 59, tzinfo=UTC)
    )

    data = await usage(client, **{"from": "2026-09-24", "to": "2026-09-25"})

    assert data["timezone"] == "Asia/Bangkok"
    assert data["daily"] == [
        {"date": "2026-09-24", "requests": 1, "tokens": 100},
        {"date": "2026-09-25", "requests": 1, "tokens": 100},
    ]


async def test_splits_by_source_and_key_with_shares(client, db):
    key_id, _ = await seed_key(db, user_id=ALICE)
    at = datetime(2026, 9, 25, 3, tzinfo=UTC)
    for _ in range(3):
        await log(db, user_id=ALICE, key_id=key_id, at=at, tokens=200)
    await log(db, user_id=ALICE, source="web", at=at, tokens=1000)

    data = await usage(client)

    assert data["from"] == "2026-09-19" and data["to"] == "2026-09-25"
    assert len(data["daily"]) == 7
    assert data["totals"] == {"requests": 4, "tokens": 1600}
    assert data["by_source"] == [
        {"source": "api", "requests": 3, "tokens": 600},
        {"source": "web", "requests": 1, "tokens": 1000},
    ]
    assert data["by_key"] == [
        {
            "key_id": key_id,
            "name": "seeded",
            "key_prefix": f"mthw01_{key_id}",
            "status": "active",
            "requests": 3,
            "tokens": 600,
            "request_share_pct": 75.0,
        }
    ]


async def test_key_filter_narrows_everything_but_quota(client, db):
    first, _ = await seed_key(db, user_id=ALICE)
    second, _ = await seed_key(db, user_id=ALICE)
    at = datetime(2026, 9, 25, 3, tzinfo=UTC)
    await log(db, user_id=ALICE, key_id=first, at=at)
    await log(db, user_id=ALICE, key_id=second, at=at)

    data = await usage(client, key_id=first)

    assert data["totals"]["requests"] == 1
    assert [row["key_id"] for row in data["by_key"]] == [first]


async def test_other_users_usage_and_keys_are_invisible(client, db):
    bob_key, _ = await seed_key(db, user_id=BOB)
    await seed_key(db, user_id=ALICE)
    await log(db, user_id=BOB, key_id=bob_key, at=datetime(2026, 9, 25, 3, tzinfo=UTC))

    data = await usage(client, key_id=bob_key)

    assert data["totals"] == {"requests": 0, "tokens": 0}
    assert data["by_key"] == []


async def test_range_is_clamped_to_retention_and_today(client, db):
    await seed_key(db, user_id=ALICE)

    data = await usage(client, **{"from": "2026-01-01", "to": "2026-12-31"})

    assert data["from"] == "2026-07-28"  # 60 days including today
    assert data["to"] == "2026-09-25"
    assert data["clamped"] is True
    assert len(data["daily"]) == 60


async def test_quota_defaults_then_reads_the_main_apps_hash(client, db, redis):
    await seed_key(db, user_id=ALICE)
    default = (await usage(client))["quota"]
    await redis.hset(f"quota:{ALICE}", mapping={"limit": 1000, "used": 1200})

    assert default["used"] == 0 and default["remaining"] == default["limit"]
    assert (await usage(client))["quota"] == {
        "limit": 1000,
        "used": 1200,
        "remaining": 0,
    }


async def test_malformed_quota_hash_is_503(client, db, redis):
    await seed_key(db, user_id=ALICE)
    await redis.hset(f"quota:{ALICE}", mapping={"limit": "lots", "used": 0})

    response = await client.get("/v1/usage", headers=as_user(ALICE))

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "llm_quota_unavailable"


async def test_inverted_range_is_422(client, db):
    response = await client.get(
        "/v1/usage",
        params={"from": "2026-09-25", "to": "2026-09-20"},
        headers=as_user(ALICE),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "usage_invalid_range"


async def test_days_preset_ends_today(client, db):
    await seed_key(db, user_id=ALICE)

    data = await usage(client, days=30)

    assert (data["from"], data["to"]) == ("2026-08-27", "2026-09-25")
    assert data["clamped"] is False
