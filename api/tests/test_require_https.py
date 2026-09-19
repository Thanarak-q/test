import pytest
from fastapi import Request

from app.envelope import AppError
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
    with pytest.raises(AppError) as exc_info:
        require_https(build_request("http"))

    assert exc_info.value.code == "http_https_required"
    assert exc_info.value.status_code == 400


def test_https_forwarded_proto_is_allowed():
    response = require_https(build_request("https"))

    assert response is None
