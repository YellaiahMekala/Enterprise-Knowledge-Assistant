# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""Distributed traces (NFR-07): OpenTelemetry over OTLP/HTTP, on when EKA_OTEL_ENDPOINT is set.

One trace follows a question from the edge into the core: the edge sends a W3C ``traceparent``
header, the core continues that trace for the request and adds spans for each database statement,
the embedding of the question, and the chat model call (httpx for OpenAI-compatible providers,
botocore for Bedrock). Span attributes never hold question or answer text, keys or user ids: the
SQL statements are parameterised, and the model and embedder spans carry only sizes.

Off by default; nothing is imported from OpenTelemetry unless tracing is configured.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from eka import __version__

if TYPE_CHECKING:
    from fastapi import FastAPI
    from opentelemetry.sdk.trace import TracerProvider
    from sqlalchemy.ext.asyncio import AsyncEngine

    from eka.ports.embedder import Embedder

logger = logging.getLogger(__name__)


def build_provider(
    endpoint: str | None, sample_ratio: float, *, exporter: Any = None
) -> TracerProvider | None:
    """A tracer provider exporting to ``endpoint`` (or to ``exporter`` in tests); None when off."""
    if not endpoint and exporter is None:
        return None
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
    from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

    provider = TracerProvider(
        resource=Resource.create({"service.name": "eka-core", "service.version": __version__}),
        # Follow the edge's decision when it sent one; sample new traces by ratio.
        sampler=ParentBased(TraceIdRatioBased(sample_ratio)),
    )
    if exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    else:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        assert endpoint is not None
        url = endpoint.rstrip("/") + "/v1/traces"
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=url)))
    return provider


def instrument(app: FastAPI, provider: TracerProvider, engine: AsyncEngine | None) -> None:
    """Spans for incoming requests, database statements and outgoing model calls."""
    from opentelemetry.instrumentation.botocore import BotocoreInstrumentor
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

    FastAPIInstrumentor.instrument_app(
        app, tracer_provider=provider, excluded_urls="/health/live,/health/ready"
    )
    HTTPXClientInstrumentor().instrument(tracer_provider=provider)
    BotocoreInstrumentor().instrument(tracer_provider=provider)  # type: ignore[no-untyped-call]
    if engine is not None:
        # The package pins SQLAlchemy below 2.1 and refuses to start on 2.1.x, though the event
        # hooks it uses are unchanged; test_tracing proves statements still produce spans.
        SQLAlchemyInstrumentor().instrument(
            engine=engine.sync_engine, tracer_provider=provider, skip_dep_check=True
        )
    logger.info("tracing on: spans are exported over OTLP")


class TracedEmbedder:
    """Wraps the embedder so embedding shows as its own span (local ONNX model, no HTTP call)."""

    def __init__(self, inner: Embedder, provider: TracerProvider) -> None:
        self._inner = inner
        self._tracer = provider.get_tracer("eka.embedder")
        self.model_name = inner.model_name
        self.dimension = inner.dimension

    def count_tokens(self, text: str) -> int:
        return self._inner.count_tokens(text)

    def embed_query(self, text: str) -> list[float]:
        with self._tracer.start_as_current_span("embed query") as span:
            span.set_attribute("eka.embedder.model", self.model_name)
            span.set_attribute("eka.embedder.chars", len(text))
            return self._inner.embed_query(text)

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        with self._tracer.start_as_current_span("embed documents") as span:
            span.set_attribute("eka.embedder.model", self.model_name)
            span.set_attribute("eka.embedder.count", len(texts))
            return self._inner.embed_documents(texts)
