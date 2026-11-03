"""Application factory and composition root. Run with: python -m eka

This module (with the worker, later) is the only place that chooses adapters.
"""

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from fastapi import FastAPI

from eka import __version__
from eka.adapters.db.engine import Database
from eka.adapters.db.repositories import SqlDocumentRepository
from eka.adapters.storage_local import LocalFileStore
from eka.api import documents, health, me
from eka.api.deps import DocumentServiceFactory, ReadinessCheck
from eka.api.errors import install_error_handlers
from eka.config import Settings, get_settings
from eka.domain.errors import Unavailable
from eka.domain.models import Role
from eka.logging_config import configure_logging
from eka.request_context import RequestContextMiddleware
from eka.security.auth import ApiKeyAuthenticator
from eka.services.documents import DocumentService, UploadPolicy


async def _database_not_configured() -> None:
    raise Unavailable("database is not configured")


def _document_services(settings: Settings, database: Database | None) -> DocumentServiceFactory:
    """The one place that picks the adapters behind the document service."""
    store = LocalFileStore(settings.storage_local_dir)
    policy = UploadPolicy(
        max_upload_bytes=settings.max_upload_bytes,
        max_documents=settings.max_docs_per_user,
        text_extensions=settings.allowed_text_extensions,
        max_text_bytes=settings.max_text_file_kb * 1024,
    )

    def open_for(owner_id: str, role: Role) -> AbstractAsyncContextManager[DocumentService]:
        if database is None:
            raise Unavailable("database is not configured")

        @asynccontextmanager
        async def scope() -> AsyncIterator[DocumentService]:
            async with database.session_for(owner_id, role) as session:
                yield DocumentService(SqlDocumentRepository(session), store, policy)

        return scope()

    return open_for


def create_app(
    settings: Settings | None = None, *, readiness_check: ReadinessCheck | None = None
) -> FastAPI:
    """``readiness_check`` lets tests replace the database probe; production uses the database."""
    settings = settings or get_settings()
    configure_logging(settings.log_level, json_logs=settings.log_json)

    database = Database(settings.database_url.get_secret_value()) if settings.database_url else None
    if readiness_check is None:
        readiness_check = database.ping if database else _database_not_configured

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        if database is not None:
            await database.dispose()

    # Interactive API docs are a development aid; production serves only the API itself.
    docs_enabled = settings.environment != "prod"
    app = FastAPI(
        title="Enterprise Knowledge Assistant",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )
    app.state.database = database
    app.state.authenticator = ApiKeyAuthenticator(settings.api_keys)
    app.state.readiness_check = readiness_check
    app.state.document_service_factory = _document_services(settings, database)
    app.state.max_upload_bytes = settings.max_upload_bytes

    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)
    app.include_router(health.router)
    app.include_router(me.router)
    app.include_router(documents.router)
    return app
