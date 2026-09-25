import pytest
from fastapi import HTTPException, Request

from app.services.proxy_trust import require_https


def build_request(protocol: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/reached",
            "headers": [(b"x-forwarded-proto", protocol.encode())],
            "client": ("10.0.0.10", 443),
        }
    )


def test_non_https_request_is_rejected():
    with pytest.raises(HTTPException) as exc_info:
        require_https(build_request("http"), ["10.0.0.10"])

    assert exc_info.value.status_code == 400
    # The revoke advice is the point: a request that arrived over HTTP has
    # already leaked the key, so fixing the client alone is not enough.
    assert exc_info.value.detail == (
        "HTTPS is required. Update your client to use https:// and revoke this key, "
        "as it was transmitted unencrypted."
    )


def test_https_forwarded_proto_is_allowed():
    response = require_https(build_request("https"), ["10.0.0.10"])

    assert response == "10.0.0.10"
