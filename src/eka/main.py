"""Application factory and composition root. Run with: python -m eka

This module and the worker are the only places that choose adapters.
"""

import asyncio
import os
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import datetime
from typing import TYPE_CHECKING

from fastapi import FastAPI
from pydantic import SecretStr

from eka import __version__
from eka.adapters.chat_bedrock import BedrockChat
from eka.adapters.chat_fake import FakeChatModel
from eka.adapters.chat_fallback import FallbackChatModel
from eka.adapters.chat_openai import OpenAICompatibleChat
from eka.adapters.db.engine import Database
from eka.adapters.db.repositories import (
    SqlConversationRepository,
    SqlDocumentRepository,
    SqlUsageReport,
    document_status_counts,
)
from eka.adapters.db.search import SqlChunkSearch
from eka.adapters.reranker_fastembed import FastEmbedReranker
from eka.adapters.storage import build_file_store
from eka.adapters.web_fetch import SafeFetcher
from eka.api import admin, chat, documents, health, me, search
from eka.api.deps import DocumentServiceFactory, ReadinessCheck
from eka.api.errors import install_error_handlers
from eka.config import FallbackModel, Settings, get_settings
from eka.domain.errors import Unavailable
from eka.domain.models import Role, UsageRow
from eka.logging_config import configure_logging
from eka.metrics import Metrics
from eka.ports.chat import ChatModel
from eka.ports.embedder import Embedder
from eka.ports.reranker import Reranker
from eka.request_context import RequestContextMiddleware
from eka.tracing import TracedEmbedder, build_provider, instrument

if TYPE_CHECKING:
    from opentelemetry.sdk.trace import TracerProvider
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


class EmbedderWarmup:
    """Loads the embedding model at start-up, in the background, so readiness can report it
    (FR-52). Until it has loaded, or when loading failed, the service is not ready: it could take
    documents but not answer or search."""

    def __init__(self, provider: EmbedderProvider) -> None:
        self._provider = provider
        self._task: asyncio.Future[Embedder] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.ensure_future(self._provider())

    async def check(self) -> None:
        if self._task is None or not self._task.done():
            raise Unavailable("the embedding model is still loading")
        if self._task.cancelled() or self._task.exception() is not None:
            raise Unavailable("the embedding model could not be loaded")

    async def stop(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()


def _readiness(database_check: ReadinessCheck, warmup: EmbedderWarmup) -> ReadinessCheck:
    async def check() -> None:
        await database_check()
        await warmup.check()

    return check


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


def _chat_model(
    settings: Settings, given: ChatModel | None, metrics: Metrics | None = None
) -> ChatModel:
    """The fake model by default; a live one (OpenAI-compatible or Bedrock) only when configured.
    With EKA_CHAT_FALLBACKS the models are wrapped in a fallback chain (ADR-038)."""
    primary = given if given is not None else _one_model(settings)
    if not settings.chat_fallbacks:
        return primary
    models = [primary, *(_fallback_model(settings, f) for f in settings.chat_fallbacks)]
    return FallbackChatModel(models, observer=metrics)


def _fallback_model(settings: Settings, fallback: FallbackModel) -> ChatModel:
    key = os.environ.get(fallback.api_key_env, "") if fallback.api_key_env else ""
    if fallback.provider == "openai" and not key:
        raise ValueError(f"the fallback key variable {fallback.api_key_env} is empty")
    return _one_model(
        settings.model_copy(
            update={
                "chat_provider": fallback.provider,
                "chat_model": fallback.model,
                "chat_base_url": fallback.base_url or settings.chat_base_url,
                "chat_api_key": SecretStr(key) if key else None,
            }
        )
    )


def _one_model(settings: Settings) -> ChatModel:
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


def _usage_report(
    database: Database | None,
) -> Callable[[str, str, datetime, datetime], Awaitable[list[UsageRow]]]:
    """The admin usage report, read in a session opened with the admin role (ADR-037)."""

    async def report(
        owner_id: str, group_by: str, start: datetime, end: datetime
    ) -> list[UsageRow]:
        if database is None:
            raise Unavailable("database is not configured")
        async with database.session_for(owner_id, Role.ADMIN) as session:
            return await SqlUsageReport(session).summary(group_by, start, end)

    return report


def _document_counts(database: Database | None) -> Callable[[str], Awaitable[dict[str, int]]]:
    async def counts(owner_id: str) -> dict[str, int]:
        if database is None:
            raise Unavailable("database is not configured")
        async with database.session_for(owner_id, Role.ADMIN) as session:
            return await document_status_counts(session)

    return counts


def _answer_service(
    settings: Settings,
    database: Database | None,
    model: ChatModel,
    embedder: EmbedderProvider,
    metrics: Metrics | None = None,
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
            price_input_per_1m=settings.chat_price_input_per_1m,
            price_output_per_1m=settings.chat_price_output_per_1m,
        ),
        web=_web_fallback(settings, database),
        on_usage=metrics.observe_answer if metrics is not None else None,
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


def _traced(provider: EmbedderProvider, tracer_provider: "TracerProvider") -> EmbedderProvider:
    """Wraps whatever embedder the provider returns so embedding gets its own span."""
    wrapped: list[Embedder] = []

    async def get() -> Embedder:
        if not wrapped:
            wrapped.append(TracedEmbedder(await provider(), tracer_provider))
        return wrapped[0]

    return get


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
    metrics = Metrics()
    model = _chat_model(settings, chat_model, metrics)
    tracer_provider = build_provider(settings.otel_endpoint, settings.otel_sample_ratio)
    embedder_provider = _embedder_provider(settings, embedder)
    if tracer_provider is not None:
        embedder_provider = _traced(embedder_provider, tracer_provider)
    warmup = EmbedderWarmup(embedder_provider)
    if readiness_check is None:
        database_check = database.ping if database else _database_not_configured
        # Ready means: the database answers and the embedding model is loaded (FR-52).
        readiness_check = (
            _readiness(database_check, warmup)
            if settings.ready_requires_embedder
            else database_check
        )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if settings.ready_requires_embedder:
            warmup.start()
        yield
        await warmup.stop()
        if isinstance(model, OpenAICompatibleChat | FallbackChatModel):
            await model.aclose()
        if database is not None:
            await database.dispose()
        if tracer_provider is not None:
            tracer_provider.shutdown()

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
    app.state.metrics = metrics
    app.state.answer_service = answer_service or _answer_service(
        settings, database, model, embedder_provider, app.state.metrics
    )
    app.state.max_upload_bytes = settings.max_upload_bytes
    app.state.usage_report = _usage_report(database)
    app.state.document_counts = _document_counts(database)

    app.state.settings = settings
    app.state.started_at = time.monotonic()
    app.add_middleware(RequestContextMiddleware, metrics=app.state.metrics)
    install_error_handlers(app)
    if tracer_provider is not None:
        instrument(app, tracer_provider, database.engine if database else None)
    app.include_router(health.router)
    app.include_router(me.router)
    app.include_router(admin.router)
    app.include_router(documents.router)
    app.include_router(search.router)
    app.include_router(chat.router)
    return app
