from fastapi import Request
from redis.asyncio import Redis


async def get_redis(request: Request) -> Redis:
    # The client is created once in main.py's lifespan so it is opened and
    # closed with the app. A second module-level client would hold its own
    # pool that nothing ever closes.
    return request.app.state.redis
