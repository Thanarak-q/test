"""Seed helpers for tests that run against the real database."""

import hashlib
import secrets
import string
from datetime import UTC, datetime

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import ApiKey, User

ALICE, BOB = 101, 202

_BASE62 = string.ascii_letters + string.digits
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_token() -> tuple[str, str, str]:
    """(key_id, secret, token) in the real format."""
    key_id = "0" + "".join(secrets.choice(_CROCKFORD) for _ in range(25))
    secret = "".join(secrets.choice(_BASE62) for _ in range(32))
    return key_id, secret, f"mthw01_{key_id}_{secret}"


async def seed_key(
    factory: async_sessionmaker[AsyncSession],
    *,
    user_id: int,
    status: str = "active",
) -> tuple[str, str]:
    """Insert a user (if needed) and a key. Returns (key_id, token)."""
    key_id, secret, token = new_token()
    async with factory.begin() as session:
        await session.execute(insert(User).prefix_with("IGNORE").values(id=user_id))
        await session.execute(
            insert(ApiKey).values(
                id=key_id,
                user_id=user_id,
                name="seeded",
                key_hash=hashlib.sha256(secret.encode()).hexdigest(),
                status=status,
                created_at=datetime.now(UTC),
            )
        )
    return key_id, token


def as_user(user_id: int) -> dict[str, str]:
    """Headers for the test session stand-in (see tests/repos/conftest.py)."""
    return {"X-Test-User": str(user_id), "X-Real-IP": "203.0.113.7"}
