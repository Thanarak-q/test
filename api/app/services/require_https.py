from fastapi import Request
from fastapi.responses import JSONResponse

HTTPS_REQUIRED_BODY = {
    "error": {
        "type": "invalid_request",
        "message": "HTTPS is required. Update your client to use https://",
    }
}


def require_https(request: Request) -> JSONResponse | None:
    protocol = request.headers.get("X-Forwarded-Proto")
    if protocol == "https":
        return None
    return JSONResponse(status_code=400, content=HTTPS_REQUIRED_BODY)
