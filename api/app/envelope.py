import json
import logging
from collections.abc import Callable, Coroutine
from typing import Any, Generic, TypeVar

from fastapi import FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel
from starlette.exceptions import HTTPException

logger = logging.getLogger(__name__)

T = TypeVar("T")


class Pagination(BaseModel):
    total: int
    page: int
    limit: int


class ErrorBody(BaseModel):
    code: str
    message: str


class Envelope(BaseModel, Generic[T]):
    success: bool
    data: T | None = None
    error: ErrorBody | None = None
    meta: Pagination | None = None


class AppError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.headers = headers


def error_response(
    code: str,
    message: str,
    status_code: int,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "data": None,
            "error": {"code": code, "message": message},
            "meta": None,
        },
        headers=headers,
    )


def _is_wrappable(response: Response) -> bool:
    # A route declaring a return type gets a pre-serialized plain `Response`, not a
    # JSONResponse — so this matches on the content type, not the class.
    if isinstance(response, StreamingResponse | FileResponse):
        return False
    if response.status_code < 200 or response.status_code in (204, 304):
        return False
    media_type = response.headers.get("content-type", "")
    return media_type.startswith("application/json") and bool(response.body)


class EnvelopeRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def wrapped(request: Request) -> Response:
            response = await original(request)
            if not _is_wrappable(response):
                return response

            payload = json.loads(response.body)
            if isinstance(payload, dict) and "success" in payload:
                return response

            meta = (
                payload.pop("pagination", None) if isinstance(payload, dict) else None
            )
            return JSONResponse(
                status_code=response.status_code,
                content={"success": True, "data": payload, "error": None, "meta": meta},
            )

        return wrapped


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return error_response(exc.code, exc.message, exc.status_code, exc.headers)

    @app.exception_handler(HTTPException)
    async def _http_error(_: Request, exc: HTTPException) -> JSONResponse:
        return error_response(
            f"http_{exc.status_code}",
            str(exc.detail),
            exc.status_code,
            exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return error_response(
            "validation_error",
            "; ".join(
                f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()
            ),
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        return error_response(
            "internal_error",
            "Something went wrong.",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
