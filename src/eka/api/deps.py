"""FastAPI dependencies. Wiring objects are read from ``app.state``, set once by ``create_app``."""

import logging
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request, Security
from fastapi.security import APIKeyHeader

from eka.domain.errors import Unauthorized
from eka.request_context import current_context
from eka.security.auth import ApiKeyAuthenticator, Principal

logger = logging.getLogger(__name__)

ReadinessCheck = Callable[[], Awaitable[None]]

# auto_error=False: the scheme documents the header in OpenAPI; our handler produces the 401.
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_authenticator(request: Request) -> ApiKeyAuthenticator:
    authenticator: ApiKeyAuthenticator = request.app.state.authenticator
    return authenticator


def get_readiness_check(request: Request) -> ReadinessCheck:
    check: ReadinessCheck = request.app.state.readiness_check
    return check


# ``async def`` on purpose: it runs on the event loop, so the user id set below is visible to
# the access log written after the response.
async def get_principal(
    authenticator: Annotated[ApiKeyAuthenticator, Depends(get_authenticator)],
    api_key: Annotated[str | None, Security(_api_key_header)] = None,
) -> Principal:
    principal = authenticator.authenticate(api_key)
    if principal is None:
        # The reason is logged; the client only learns that the credential was not accepted.
        logger.warning("authentication failed: %s", "no key" if not api_key else "unknown key")
        raise Unauthorized()
    ctx = current_context()
    if ctx is not None:
        ctx.user_id = principal.user_id
    return principal


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
