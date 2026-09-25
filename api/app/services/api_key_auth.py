"""Wires validate_api_key to the real Redis and MySQL adapters."""

from redis.asyncio import Redis

from app.db import SessionLocal
from app.repos.auth_cache import RedisAuthCache
from app.repos.auth_database import SqlAuthDatabase, SqlFailureAudit
from app.services.validate_api_key import AuthIdentity, validate_api_key


async def authenticate(token: str, client_ip: str, redis: Redis) -> AuthIdentity:
    return await validate_api_key(
        token,
        client_ip,
        cache=RedisAuthCache(redis),
        database=SqlAuthDatabase(SessionLocal),
        audit=SqlFailureAudit(SessionLocal),
    )
