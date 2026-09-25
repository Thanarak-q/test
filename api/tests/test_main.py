from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.envelope import EnvelopeRoute
from app.main import app


def test_health_is_unversioned_and_needs_no_redis():
    # No lifespan: health must answer without Redis or the database.
    response = TestClient(app, base_url="http://localhost").get("/health")

    assert response.status_code == 200
    assert response.json()["data"] == {"status": "ok"}
    assert response.headers["Cache-Control"] == "no-store"


def test_health_is_not_under_v1():
    response = TestClient(app, base_url="http://localhost").get("/v1/health")

    assert response.status_code == 404


def test_every_api_route_is_enveloped():
    # include_router keeps a route's own class; a router that forgets
    # route_class=EnvelopeRoute silently returns bare JSON.
    api_routes = list(_api_routes(app.routes))

    assert api_routes  # the walker below broke if this finds nothing
    unwrapped = {r.path for r in api_routes if not isinstance(r, EnvelopeRoute)}
    # The exceptions: OpenAI-compatible replies, or the SDKs cannot read them.
    assert unwrapped == {"/v1/chat/completions", "/v1/embeddings"}


def _api_routes(routes):
    # FastAPI 0.14x keeps an included router as one `_IncludedRouter` entry
    # pointing at the original router instead of copying its routes in.
    for route in routes:
        included = getattr(route, "original_router", None)
        if included is not None:
            yield from _api_routes(included.routes)
        elif isinstance(route, APIRoute):
            yield route
