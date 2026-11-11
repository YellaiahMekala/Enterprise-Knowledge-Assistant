"""Application factory and composition root. Run with: python -m eka

This module and the worker are the only places that choose adapters.
"""

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from fastapi import FastAPI

from eka import __version__
from eka.adapters.chat_bedrock import BedrockChat
from eka.adapters.chat_fake import FakeChatModel
from eka.adapters.chat_openai import OpenAICompatibleChat
from eka.adapters.db.engine import Database
from eka.adapters.db.repositories import SqlConversationRepository, SqlDocumentRepository
from eka.adapters.db.search import SqlChunkSearch
from eka.adapters.reranker_fastembed import FastEmbedReranker
from eka.adapters.storage import build_file_store
from eka.adapters.web_fetch import SafeFetcher
from eka.api import admin, chat, documents, health, me, search
from eka.api.deps import DocumentServiceFactory, ReadinessCheck
from eka.api.errors import install_error_handlers
from eka.config import Settings, get_settings
from eka.domain.errors import Unavailable
from eka.domain.models import Role
from eka.logging_config import configure_logging
from eka.metrics import Metrics
from eka.ports.chat import ChatModel
from eka.ports.embedder import Embedder
from eka.ports.reranker import Reranker
from eka.request_context import RequestContextMiddleware
from eka.security.auth import ApiKeyAuthenticator
from eka.security.gateway import GatewayAuthenticator
from eka.services.answering import AnswerScope, AnswerService, AnswerSettings
from eka.services.documents import DocumentService, UploadPolicy
from eka.services.retrieval import (
    EmbedderProvider,
    RetrievalService,
    RetrievalServiceFactory,
    RetrievalSettings,
)
from eka.services.web_fallback import WebFallback, WebSettings


async def _database_not_configured() -> None:
    raise Unavailable("database is not configured")


def _document_services(settings: Settings, database: Database | None) -> DocumentServiceFactory:
    """The one place that picks the adapters behind the document service."""
    store = build_file_store(settings)
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


def _web_fallback(settings: Settings, database: Database | None) -> WebFallback | None:
    if not settings.web_fallback_enabled:
        return None
    fetcher = SafeFetcher(
        settings.web_allowed_hosts,
        max_bytes=settings.web_max_page_kb * 1024,
        timeout_seconds=settings.web_fetch_timeout_seconds,
    )
    return WebFallback(
        fetcher,
        _document_services(settings, database),
        WebSettings(
            entry_urls=settings.web_entry_urls,
            refresh_hours=settings.web_refresh_hours,
            wait_seconds=settings.web_ingest_wait_seconds,
            max_text_bytes=settings.max_text_file_kb * 1024,
        ),
    )


def _reranker(settings: Settings) -> Reranker | None:
    if settings.reranker_model is None:
        return None
    return FastEmbedReranker(settings.reranker_model, settings.embedding_cache_dir)


def _retrieval_services(settings: Settings, database: Database | None) -> RetrievalServiceFactory:
    retrieval = RetrievalSettings(
        candidates=settings.retrieval_candidates,
        rrf_k=settings.rrf_k,
        exact_max_chunks=settings.exact_search_max_chunks,
        ef_search=settings.hnsw_ef_search,
        rerank_top=settings.reranker_top,
    )
    reranker = _reranker(settings)

    def open_for(
        owner_id: str, role: Role, embedder: Embedder
    ) -> AbstractAsyncContextManager[RetrievalService]:
        if database is None:
            raise Unavailable("database is not configured")

        @asynccontextmanager
        async def scope() -> AsyncIterator[RetrievalService]:
            async with database.session_for(owner_id, role) as session:
                yield RetrievalService(SqlChunkSearch(session), embedder, retrieval, reranker)

        return scope()

    return open_for


def _chat_model(settings: Settings, given: ChatModel | None) -> ChatModel:
    """The fake model by default; a live one (OpenAI-compatible or Bedrock) only when configured."""
    if given is not None:
        return given
    if settings.chat_provider == "openai":
        assert settings.chat_model is not None and settings.chat_api_key is not None
        return OpenAICompatibleChat(
            base_url=settings.chat_base_url,
            api_key=settings.chat_api_key.get_secret_value(),
            model=settings.chat_model,
            timeout_seconds=settings.chat_timeout_seconds,
            retries=settings.chat_retries,
        )
    if settings.chat_provider == "bedrock":
        assert settings.chat_model is not None
        return BedrockChat(
            model_id=settings.chat_model,
            region=settings.bedrock_region,
            endpoint_url=settings.bedrock_endpoint_url,
            timeout_seconds=settings.chat_timeout_seconds,
            retries=settings.chat_retries,
        )
    return FakeChatModel()


def _answer_service(
    settings: Settings,
    database: Database | None,
    model: ChatModel,
    embedder: EmbedderProvider,
) -> AnswerService:
    retrieval = RetrievalSettings(
        candidates=settings.retrieval_candidates,
        rrf_k=settings.rrf_k,
        exact_max_chunks=settings.exact_search_max_chunks,
        ef_search=settings.hnsw_ef_search,
        rerank_top=settings.reranker_top,
    )
    reranker = _reranker(settings)

    def open_for(owner_id: str, role: Role) -> AbstractAsyncContextManager[AnswerScope]:
        if database is None:
            raise Unavailable("database is not configured")

        @asynccontextmanager
        async def scope() -> AsyncIterator[AnswerScope]:
            async with database.session_for(owner_id, role) as session:
                search = SqlChunkSearch(session)
                yield AnswerScope(
                    conversations=SqlConversationRepository(session),
                    retrieval=lambda embedder_: RetrievalService(
                        search, embedder_, retrieval, reranker
                    ),
                )

        return scope()

    return AnswerService(
        open_for,
        model,
        embedder,
        AnswerSettings(
            default_mode=settings.answer_mode,
            min_cosine=settings.refusal_min_cosine,
            context_passages=settings.context_passages,
            max_context_chars=settings.max_context_chars,
            history_messages=settings.history_messages,
            max_output_tokens=settings.max_output_tokens,
        ),
        web=_web_fallback(settings, database),
    )


def _embedder_provider(settings: Settings, given: Embedder | None) -> EmbedderProvider:
    """Returns ``given`` if set, otherwise loads the embedding model on first use."""
    if given is not None:

        async def provided() -> Embedder:
            return given

        return provided

    loaded: list[Embedder] = []
    lock = asyncio.Lock()

    async def load() -> Embedder:
        if not loaded:
            async with lock:
                if not loaded:
                    # Imported here to avoid loading the ONNX runtime unless a search happens.
                    from eka.adapters.embedder_fastembed import FastEmbedEmbedder

                    loaded.append(
                        await asyncio.to_thread(
                            FastEmbedEmbedder,
                            settings.embedding_model,
                            settings.embedding_cache_dir,
                            settings.embedding_dim,
                            query_prefix=settings.embedding_query_prefix,
                        )
                    )
        return loaded[0]

    return load


def create_app(
    settings: Settings | None = None,
    *,
    readiness_check: ReadinessCheck | None = None,
    embedder: Embedder | None = None,
    chat_model: ChatModel | None = None,
    answer_service: AnswerService | None = None,
    gateway_authenticator: GatewayAuthenticator | None = None,
) -> FastAPI:
    """The keyword arguments let tests replace the database probe, the two models, or the whole
    answer service."""
    settings = settings or get_settings()
    configure_logging(settings.log_level, json_logs=settings.log_json)

    database = Database(settings.database_url.get_secret_value()) if settings.database_url else None
    if readiness_check is None:
        readiness_check = database.ping if database else _database_not_configured

    model = _chat_model(settings, chat_model)
    embedder_provider = _embedder_provider(settings, embedder)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        if isinstance(model, OpenAICompatibleChat):
            await model.aclose()
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
    if settings.auth_mode == "gateway":
        app.state.authenticator = gateway_authenticator or GatewayAuthenticator.from_jwks_url(
            str(settings.gateway_jwks_url), settings.gateway_issuer, settings.gateway_audience
        )
    else:
        app.state.authenticator = ApiKeyAuthenticator(settings.api_keys)
    app.state.readiness_check = readiness_check
    app.state.document_service_factory = _document_services(settings, database)
    app.state.retrieval_service_factory = _retrieval_services(settings, database)
    app.state.embedder_provider = embedder_provider
    app.state.answer_service = answer_service or _answer_service(
        settings, database, model, embedder_provider
    )
    app.state.max_upload_bytes = settings.max_upload_bytes

    app.state.settings = settings
    app.state.started_at = time.monotonic()
    app.state.metrics = Metrics()
    app.add_middleware(RequestContextMiddleware, metrics=app.state.metrics)
    install_error_handlers(app)
    app.include_router(health.router)
    app.include_router(me.router)
    app.include_router(admin.router)
    app.include_router(documents.router)
    app.include_router(search.router)
    app.include_router(chat.router)
    return app
