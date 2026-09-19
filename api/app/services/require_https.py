from fastapi import Request

from app.envelope import AppError


def require_https(request: Request) -> None:
    protocol = request.headers.get("X-Forwarded-Proto")
    if protocol == "https":
        return
    raise AppError(
        "http_https_required",
        "HTTPS is required. Update your client to use https://",
    )
