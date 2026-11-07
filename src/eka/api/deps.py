"""FastAPI dependencies. Wiring objects are read from ``app.state``, set once by ``create_app``."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Annotated

from fastapi import Depends, Request, Security
from fastapi.security import APIKeyHeader

from eka.domain.errors import Unauthorized
from eka.domain.models import Role
from eka.request_context import current_context
from eka.security.auth import ApiKeyAuthenticator, Principal
from eka.security.gateway import GatewayAuthenticator
from eka.services.answering import AnswerService
from eka.services.documents import DocumentService
from eka.services.retrieval import EmbedderProvider, RetrievalServiceFactory

Authenticator = ApiKeyAuthenticator | GatewayAuthenticator

logger = logging.getLogger(__name__)

ReadinessCheck = Callable[[], Awaitable[None]]
# Opens one transaction scoped to a user and yields a service bound to it (built in main.py).
DocumentServiceFactory = Callable[[str, Role], AbstractAsyncContextManager[DocumentService]]


def get_document_service_factory(request: Request) -> DocumentServiceFactory:
    factory: DocumentServiceFactory = request.app.state.document_service_factory
    return factory


def get_retrieval_service_factory(request: Request) -> RetrievalServiceFactory:
    factory: RetrievalServiceFactory = request.app.state.retrieval_service_factory
    return factory


def get_embedder_provider(request: Request) -> EmbedderProvider:
    provider: EmbedderProvider = request.app.state.embedder_provider
    return provider


def get_answer_service(request: Request) -> AnswerService:
    service: AnswerService = request.app.state.answer_service
    return service


def get_max_upload_bytes(request: Request) -> int:
    limit: int = request.app.state.max_upload_bytes
    return limit


# auto_error=False: the scheme documents the header in OpenAPI; our handler produces the 401.
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_authenticator(request: Request) -> Authenticator:
    authenticator: Authenticator = request.app.state.authenticator
    return authenticator


def get_readiness_check(request: Request) -> ReadinessCheck:
    check: ReadinessCheck = request.app.state.readiness_check
    return check


# ``async def`` on purpose: it runs on the event loop, so the user id set below is visible to
# the access log written after the response.
async def get_principal(
    request: Request,
    authenticator: Annotated[Authenticator, Depends(get_authenticator)],
    api_key: Annotated[str | None, Security(_api_key_header)] = None,
) -> Principal:
    if isinstance(authenticator, GatewayAuthenticator):
        scheme, _, bearer = request.headers.get("authorization", "").partition(" ")
        credential = bearer.strip() if scheme.lower() == "bearer" else None
        # Key-set retrieval is blocking and cached; keep it off the event loop.
        principal = await asyncio.to_thread(authenticator.authenticate, credential)
    else:
        credential = api_key
        principal = authenticator.authenticate(credential)
    if principal is None:
        # The reason is logged; the client only learns that the credential was not accepted.
        logger.warning(
            "authentication failed: %s", "no credential" if not credential else "unknown credential"
        )
        raise Unauthorized()
    ctx = current_context()
    if ctx is not None:
        ctx.user_id = principal.user_id
    return principal


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


DocumentServices = Annotated[DocumentServiceFactory, Depends(get_document_service_factory)]
MaxUploadBytes = Annotated[int, Depends(get_max_upload_bytes)]
RetrievalServices = Annotated[RetrievalServiceFactory, Depends(get_retrieval_service_factory)]
EmbedderFor = Annotated[EmbedderProvider, Depends(get_embedder_provider)]
AnswerServices = Annotated[AnswerService, Depends(get_answer_service)]
