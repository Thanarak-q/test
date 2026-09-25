from collections.abc import AsyncIterator
from datetime import UTC, datetime

from sqlalchemy import DateTime
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator

from app.config import settings
from app.constants.infra import DB_CONNECT_TIMEOUT_SECONDS, DB_POOL_TIMEOUT_SECONDS

# docs/NON_FUNCTIONAL.md §2.2 — never hold a pooled connection during the
# provider call. get_session keeps one for the whole request, so the chat
# route does not use it: every read and write there opens its own short
# session from SessionLocal, and none is open while the provider is called.
# pool_timeout keeps an exhausted pool a fast 503 rather than a queue.
engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_recycle=1800,
    pool_timeout=DB_POOL_TIMEOUT_SECONDS,
    # Server-side NOW() follows the session zone; pin it so anything SQL-side
    # agrees with the UTC the app writes. The app still sets every timestamp.
    connect_args={
        "init_command": "SET time_zone = '+00:00'",
        "connect_timeout": DB_CONNECT_TIMEOUT_SECONDS,
    },
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class UtcDateTime(TypeDecorator[datetime]):
    """A timezone-aware datetime stored as UTC.

    MySQL DATETIME has no zone, so the driver hands back naive values, and
    code that validates records (validate_api_key among them) rightly rejects
    naive datetimes. This is the one place zones are handled on the way in and
    out: writes must be aware and are normalised to UTC, reads come back
    tagged UTC. Microsecond precision so "newest first" is stable.
    """

    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "mysql":
            return dialect.type_descriptor(DATETIME(fsp=6))
        return dialect.type_descriptor(DateTime())

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime: pass an aware datetime (UTC)")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        return None if value is None else value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    type_annotation_map = {datetime: UtcDateTime}


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        async with session.begin():
            yield session


async def get_unbegun_session() -> AsyncIterator[AsyncSession]:
    """A session whose transaction the service opens and commits itself.

    For work that must do something after the commit is durable — API key
    revocation invalidates the auth cache only once the new status is
    committed, otherwise a concurrent lookup could re-cache the old one.
    """
    async with SessionLocal() as session:
        yield session
