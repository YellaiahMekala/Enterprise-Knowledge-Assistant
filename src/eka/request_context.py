"""Per-request context: a request id, the caller's id once known, and one access-log line.

Implemented as a plain ASGI middleware (not ``BaseHTTPMiddleware``) so streaming responses added
later are not buffered. Inbound ``X-Request-Id`` headers are ignored in standalone mode: a
client-chosen id would be a log-injection vector. (In edge mode the edge's id is used; P3b.)
"""

import logging
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-Id"
_access_logger = logging.getLogger("eka.access")


@dataclass
class RequestContext:
    request_id: str
    user_id: str | None = None  # pseudonymous id from the credential; set by the auth dependency


_current: ContextVar[RequestContext | None] = ContextVar("eka_request_context", default=None)


def current_context() -> RequestContext | None:
    return _current.get()


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        ctx = RequestContext(request_id=uuid.uuid4().hex)
        # Exception handlers that run outside this middleware (500s) read the id from here.
        scope.setdefault("state", {})["request_id"] = ctx.request_id
        token = _current.set(ctx)
        started = time.perf_counter()
        status = 500

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = MutableHeaders(scope=message)
                if REQUEST_ID_HEADER not in headers:
                    headers[REQUEST_ID_HEADER] = ctx.request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            # The route *template* is logged, never the raw path: it is bounded and carries no ids.
            route = getattr(scope.get("route"), "path", None)
            if route is None:
                # No API route matched: a 404/405, or a built-in page such as /docs.
                route = "unmatched" if status in (404, 405) else "other"
            level = logging.DEBUG if route.startswith("/health") else logging.INFO
            _access_logger.log(
                level,
                "%s %s %s",
                scope["method"],
                route,
                status,
                extra={
                    "method": scope["method"],
                    "route": route,
                    "status": status,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                },
            )
            _current.reset(token)
