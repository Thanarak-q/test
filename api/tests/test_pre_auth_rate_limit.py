import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.services.pre_auth_rate_limit import get_trusted_proxy_ip


def build_request(headers: dict[str, str]) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [
            (key.lower().encode(), value.encode()) for key, value in headers.items()
        ],
        "client": ("10.0.0.10", 443),
        "server": ("api", 8000),
        "scheme": "http",
    }
    return Request(scope)


def test_uses_x_real_ip_from_trusted_proxy():
    request = build_request(
        {
            "X-Real-IP": "203.0.113.42",
            "X-Forwarded-For": "198.51.100.7, 203.0.113.42",
        }
    )

    assert get_trusted_proxy_ip(request, ["10.0.0.10"]) == "203.0.113.42"


def test_uses_rightmost_x_forwarded_for_value():
    request = build_request({"X-Forwarded-For": "198.51.100.7, 203.0.113.42"})

    assert get_trusted_proxy_ip(request, ["10.0.0.10"]) == "203.0.113.42"


def test_rejects_request_from_untrusted_peer():
    request = build_request({"X-Real-IP": "203.0.113.42"})

    with pytest.raises(HTTPException, match="trusted proxy"):
        get_trusted_proxy_ip(request, ["10.0.0.11"])
