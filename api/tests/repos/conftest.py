import httpx
import pytest
from fastapi import Request

from app.dependencies import get_current_principal
from app.main import app
from app.services.session_auth import Principal


@pytest.fixture
async def client(db, redis):
    """The real app over ASGI, with a test stand-in for the session."""

    async def principal_from_test_header(request: Request) -> Principal:
        # Test-only stand-in for the main application's session.
        return Principal(user_id=int(request.headers["X-Test-User"]), role="user")

    app.dependency_overrides[get_current_principal] = principal_from_test_header
    app.state.redis = redis
    app.state.trusted_proxies = frozenset({"127.0.0.1"})
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as http:
        yield http
    app.dependency_overrides.clear()
