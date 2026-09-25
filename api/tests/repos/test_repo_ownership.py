"""docs/NON_FUNCTIONAL.md §1.1: every user-owned repo function, called with a
second user's id, sees and changes nothing. Real MySQL — a mock cannot show
that the WHERE clause is right."""

from datetime import UTC, datetime

from sqlalchemy import insert, select

from app.models import ApiKey, LlmUsageLog
from app.repos import api_key_repo, usage_repo
from tests.repos.helpers import ALICE, BOB, seed_key

NOW = datetime(2026, 9, 25, 3, tzinfo=UTC)


async def _alice_key(db):
    key_id, _ = await seed_key(db, user_id=ALICE)
    await seed_key(db, user_id=BOB)  # Bob exists and owns keys of his own
    return key_id


async def _status(db, key_id):
    async with db() as session:
        return await session.scalar(select(ApiKey.status).where(ApiKey.id == key_id))


async def test_touch_last_used(db):
    key_id = await _alice_key(db)
    async with db.begin() as session:
        changed = await api_key_repo.touch_last_used(
            session, key_id=key_id, user_id=BOB, at=NOW
        )
    async with db() as session:
        last_used = await session.scalar(
            select(ApiKey.last_used_at).where(ApiKey.id == key_id)
        )
    assert changed is False and last_used is None


async def test_list_for_user(db):
    key_id = await _alice_key(db)
    async with db() as session:
        listed = await api_key_repo.list_for_user(session, user_id=BOB)
    assert key_id not in {row.id for row in listed}


async def test_get_status(db):
    key_id = await _alice_key(db)
    async with db() as session:
        assert (
            await api_key_repo.get_status(session, key_id=key_id, user_id=BOB) is None
        )


async def test_revoke(db):
    key_id = await _alice_key(db)
    async with db.begin() as session:
        changed = await api_key_repo.revoke(session, key_id=key_id, user_id=BOB, at=NOW)
    assert changed is False and await _status(db, key_id) == "active"


async def test_soft_delete(db):
    key_id = await _alice_key(db)
    async with db.begin() as session:
        changed = await api_key_repo.soft_delete(
            session, key_id=key_id, user_id=BOB, at=NOW
        )
    assert changed is False and await _status(db, key_id) == "active"


async def test_labels_for_user(db):
    key_id = await _alice_key(db)
    async with db() as session:
        labels = await api_key_repo.labels_for_user(
            session, user_id=BOB, key_ids=[key_id]
        )
    assert labels == []


async def test_insert_limit_counts_only_the_users_own_keys(db):
    for _ in range(5):
        await seed_key(db, user_id=ALICE)
    await seed_key(db, user_id=BOB)
    async with db.begin() as session:
        inserted = await api_key_repo.insert_if_under_limit(
            session,
            key_id="01K5ZQ3NDEKTSV4RRFFQ69G5FZ",
            user_id=BOB,
            name="bob's second",
            key_hash="b" * 64,
            created_at=NOW,
            max_active=5,
        )
    assert inserted is True  # Alice's five do not count against Bob


async def test_hourly_usage(db):
    key_id = await _alice_key(db)
    async with db.begin() as session:
        await session.execute(
            insert(LlmUsageLog).values(
                user_id=ALICE,
                source="api",
                key_id=key_id,
                tokens=2,
                created_at=NOW,
            )
        )

    async with db() as session:
        usage = await usage_repo.hourly_for_user(
            session,
            user_id=BOB,
            start=datetime(2026, 9, 1, tzinfo=UTC),
            end=datetime(2026, 10, 1, tzinfo=UTC),
            key_id=key_id,
        )
        own = await usage_repo.hourly_for_user(
            session,
            user_id=ALICE,
            start=datetime(2026, 9, 1, tzinfo=UTC),
            end=datetime(2026, 10, 1, tzinfo=UTC),
            key_id=None,
        )

    assert usage == []
    assert [(row.hour, row.requests, row.tokens) for row in own] == [(NOW, 1, 2)]
