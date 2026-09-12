import json

from fastapi import Request

from app.services.require_https import require_https


def build_request(protocol: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/reached",
            "headers": [(b"x-forwarded-proto", protocol.encode())],
        }
    )


def test_non_https_request_is_rejected():
    response = require_https(build_request("http"))

    assert response is not None
    assert response.status_code == 400
    assert json.loads(response.body) == {
        "error": {
            "type": "invalid_request",
            "message": "HTTPS is required. Update your client to use https://",
        }
    }


def test_https_forwarded_proto_is_allowed():
    response = require_https(build_request("https"))

    assert response is None
