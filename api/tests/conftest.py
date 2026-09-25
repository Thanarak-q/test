"""Test configuration and the real-infrastructure fixtures.

Tests that prove fail-closed and ownership run against the compose MySQL and
Redis, never fakes: a fake cannot show what the real client raises or what the
real database lets through. Start them with `docker compose up -d`.

Without them those tests skip — unless REQUIRE_INFRA=1 (set it in CI), which
turns a missing service into a failure so the proof cannot silently vanish.
"""

import asyncio
import os
from urllib.parse import urlsplit

import pytest

# Forced, not setdefault: a developer's own DATABASE_URL must never be the
# database these tests truncate.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "mysql+aiomysql://root:matthew@127.0.0.1:3310/matthew_test?charset=utf8mb4",
)
TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://127.0.0.1:6389/15")
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["REDIS_URL"] = TEST_REDIS_URL
os.environ.setdefault("ENV", "test")

REQUIRE_INFRA = os.environ.get("REQUIRE_INFRA") == "1"

_TABLES = (
    "identity_api_key_audit_logs",
    "identity_auth_failure_logs",
    "identity_api_keys",
    "llm_usage_logs",
    "llm_provider_call_logs",
    "llm_model_audit_logs",
    "identity_users",
)


def _unavailable(what: str, error: Exception) -> None:
    message = f"{what} unavailable ({error!r}); run `docker compose up -d`"
    if REQUIRE_INFRA:
        pytest.fail(message)
    pytest.skip(message)


async def _recreate_database() -> None:
    import aiomysql

    url = urlsplit(TEST_DATABASE_URL.replace("mysql+aiomysql", "mysql"))
    connection = await aiomysql.connect(
        host=url.hostname,
        port=url.port or 3306,
        user=url.username,
        password=url.password or "",
        connect_timeout=2,
    )
    try:
        async with connection.cursor() as cursor:
            name = url.path.lstrip("/")
            await cursor.execute(f"DROP DATABASE IF EXISTS `{name}`")
            await cursor.execute(
                f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 "
                "COLLATE utf8mb4_0900_ai_ci"
            )
    finally:
        connection.close()


@pytest.fixture(scope="session")
def _migrated_database():
    """A fresh database built by the real migration, once per run."""
    try:
        asyncio.run(_recreate_database())
    except Exception as exc:  # noqa: BLE001
        _unavailable("MySQL", exc)
        return

    from alembic.config import Config

    from alembic import command

    config = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    config.set_main_option(
        "script_location", os.path.join(os.path.dirname(__file__), "..", "alembic")
    )
    command.upgrade(config, "head")


@pytest.fixture
async def db(_migrated_database):
    """Empty tables, and the app's engine rebound to this test's event loop."""
    from sqlalchemy import text

    from app.db import SessionLocal, engine

    await engine.dispose()
    async with SessionLocal.begin() as session:
        await session.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        for table in _TABLES:
            await session.execute(text(f"TRUNCATE TABLE {table}"))
        # The migration seeds the whitelist; tests may disable models or add
        # their own, so put it back to exactly the seed.
        await session.execute(text("DELETE FROM llm_models WHERE id > 2"))
        await session.execute(
            text(
                "UPDATE llm_models SET status = 'enabled', "
                "context_window = CASE name WHEN 'gpt-4o' THEN 128000 "
                "ELSE 1047576 END, "
                "max_output_tokens = CASE name WHEN 'gpt-4o' THEN 16384 "
                "ELSE 32768 END"
            )
        )
        await session.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
    yield SessionLocal
    await engine.dispose()


@pytest.fixture
async def redis():
    from redis.asyncio import Redis
    from redis.exceptions import RedisError

    client = Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    try:
        await client.ping()
    except RedisError as exc:
        await client.aclose()
        _unavailable("Redis", exc)
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()


@pytest.fixture
def unreachable_redis():
    """A real client pointed at a port nothing listens on."""
    from redis.asyncio import Redis

    return Redis.from_url(
        "redis://127.0.0.1:1/0", decode_responses=True, socket_connect_timeout=1
    )
