import httpx
import pytest
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from httpx import ASGITransport

from app.envelope import AppError, EnvelopeRoute, register_error_handlers


def build_app() -> FastAPI:
    app = FastAPI()
    app.router.route_class = EnvelopeRoute
    register_error_handlers(app)

    router = APIRouter(route_class=EnvelopeRoute)

    @router.get("/ok")
    async def ok() -> dict[str, int]:
        return {"value": 1}

    @router.get("/boom")
    async def boom() -> None:
        raise AppError("money_insufficient_funds", "Not enough balance", 409)

    @router.get("/missing")
    async def missing() -> None:
        raise HTTPException(status_code=404, detail="nope")

    @router.get("/stream")
    async def stream() -> StreamingResponse:
        async def body():
            yield b"data: tick\n\n"

        return StreamingResponse(body(), media_type="text/event-stream")

    app.include_router(router)
    return app


@pytest.fixture
def client():
    app = build_app()
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_success_response_is_wrapped_in_envelope(client):
    res = await client.get("/ok")

    assert res.status_code == 200
    assert res.json() == {
        "success": True,
        "data": {"value": 1},
        "error": None,
        "meta": None,
    }


async def test_app_error_returns_domain_code_and_status(client):
    res = await client.get("/boom")

    assert res.status_code == 409
    body = res.json()
    assert body["success"] is False
    assert body["data"] is None
    assert body["error"] == {
        "code": "money_insufficient_funds",
        "message": "Not enough balance",
    }


async def test_http_exception_is_shaped_as_envelope_error(client):
    res = await client.get("/missing")

    assert res.status_code == 404
    assert res.json()["error"]["code"] == "http_404"


async def test_streaming_response_passes_through_unwrapped(client):
    res = await client.get("/stream")

    assert res.headers["content-type"].startswith("text/event-stream")
    assert res.text == "data: tick\n\n"
