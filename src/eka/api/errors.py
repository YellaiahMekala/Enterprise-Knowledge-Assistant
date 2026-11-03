"""One error shape for the whole API: RFC 9457 problem+json (ADR-016, TDD 6.4).

Detail is logged here and never returned. Framework errors (unknown route, wrong method,
validation) are converted so clients see a single format.
"""

import logging
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from eka.api.schemas import PROBLEM_MEDIA_TYPE
from eka.domain.errors import (
    NotFound,
    PayloadTooLarge,
    QuotaExceeded,
    Unauthorized,
    Unavailable,
    UnsupportedMedia,
)
from eka.request_context import REQUEST_ID_HEADER

logger = logging.getLogger(__name__)

_TYPE_PREFIX = "urn:eka:problem:"
_HTTP_SLUGS = {
    400: "bad-request",
    401: "unauthorized",
    403: "forbidden",
    404: "not-found",
    405: "method-not-allowed",
    413: "payload-too-large",
    415: "unsupported-media-type",
    422: "validation",
    429: "rate-limited",
}
_UNAUTHORIZED_DETAIL = "A valid API key is required."
_AUTH_CHALLENGE = {"WWW-Authenticate": "ApiKey"}


def problem(
    request: Request,
    status: int,
    *,
    slug: str | None = None,
    detail: str | None = None,
    headers: dict[str, str] | None = None,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    http_status = HTTPStatus(status)
    request_id = str(request.scope.get("state", {}).get("request_id", "-"))
    body: dict[str, Any] = {
        "type": _TYPE_PREFIX + (slug or _HTTP_SLUGS.get(status, f"http-{status}")),
        "title": http_status.phrase,
        "status": status,
        "detail": detail or http_status.description,
        "instance": request.url.path,
        "request_id": request_id,
    }
    if extra:
        body.update(extra)
    # Set the id here as well: 500 responses are produced outside the request middleware.
    response_headers = {REQUEST_ID_HEADER: request_id, **(headers or {})}
    return JSONResponse(
        body, status_code=status, media_type=PROBLEM_MEDIA_TYPE, headers=response_headers
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(Unauthorized)
    async def _unauthorized(request: Request, exc: Unauthorized) -> JSONResponse:
        return problem(request, 401, detail=_UNAUTHORIZED_DETAIL, headers=_AUTH_CHALLENGE)

    @app.exception_handler(NotFound)
    async def _not_found(request: Request, exc: NotFound) -> JSONResponse:
        return problem(request, 404, detail="No such resource.")

    @app.exception_handler(Unavailable)
    async def _unavailable(request: Request, exc: Unavailable) -> JSONResponse:
        return problem(
            request, 503, slug="unavailable", detail="A required service is unavailable."
        )

    @app.exception_handler(UnsupportedMedia)
    async def _unsupported_media(request: Request, exc: UnsupportedMedia) -> JSONResponse:
        # ``reason`` is a fixed code ("type_mismatch", ...), safe to return.
        return problem(
            request,
            415,
            detail="This file type is not supported, or the file does not match its type.",
            extra={"reason": exc.reason},
        )

    @app.exception_handler(PayloadTooLarge)
    async def _too_large(request: Request, exc: PayloadTooLarge) -> JSONResponse:
        return problem(request, 413, detail="The file is larger than the allowed size.")

    @app.exception_handler(QuotaExceeded)
    async def _quota(request: Request, exc: QuotaExceeded) -> JSONResponse:
        return problem(
            request,
            403,
            slug="quota-exceeded",
            detail="The maximum number of documents has been reached. Delete one first.",
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Field locations and messages only: the default handler also echoes the submitted input.
        errors = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
        return problem(request, 422, detail="The request is invalid.", extra={"errors": errors})

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        headers = dict(exc.headers) if exc.headers else None
        return problem(request, exc.status_code, headers=headers)

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.error("Unhandled exception", exc_info=exc)
        return problem(request, 500, slug="internal", detail="An unexpected error occurred.")
