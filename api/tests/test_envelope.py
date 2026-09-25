from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.envelope import register_error_handlers


def test_http_exception_preserves_rate_limit_headers():
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/limited")
    async def limited():
        raise HTTPException(
            status_code=429,
            detail="Too many requests.",
            headers={"RateLimit-Remaining": "0", "Retry-After": "3"},
        )

    response = TestClient(app).get("/limited")

    assert response.status_code == 429
    assert response.headers["RateLimit-Remaining"] == "0"
    assert response.headers["Retry-After"] == "3"
