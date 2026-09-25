"""Check the main application's quota:{user_id} still has the shape we use.

    uv run --directory api python -m app.jobs.quota_health

Run from cron every few minutes. It reads the quota hash of a test account
(QUOTA_HEALTH_USER_ID) and alerts — logs an ALERT line and exits 1 — if the
key is gone or `limit` / `used` are no longer integers. quota_reserve also
refuses malformed values with a 503, but this finds a schema change before a
user's request does.
"""

import asyncio
import logging
import sys

from redis.asyncio import Redis

from app.config import settings
from app.constants.infra import (
    REDIS_CONNECT_TIMEOUT_SECONDS,
    REDIS_SOCKET_TIMEOUT_SECONDS,
)
from app.services.quota import quota_schema_problems

logger = logging.getLogger(__name__)


async def check(redis: Redis, user_id: int) -> list[str]:
    problems = await quota_schema_problems(redis, user_id)
    for problem in problems:
        logger.error("ALERT quota schema: %s", problem)
    if not problems:
        logger.info("quota schema ok for user %s", user_id)
    return problems


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    if settings.quota_health_user_id is None:
        logger.error("ALERT QUOTA_HEALTH_USER_ID is not set; nothing to check")
        sys.exit(1)

    async def run() -> list[str]:
        redis = Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=REDIS_CONNECT_TIMEOUT_SECONDS,
            socket_timeout=REDIS_SOCKET_TIMEOUT_SECONDS,
        )
        try:
            return await check(redis, settings.quota_health_user_id)
        finally:
            await redis.aclose()

    sys.exit(1 if asyncio.run(run()) else 0)


if __name__ == "__main__":
    main()
