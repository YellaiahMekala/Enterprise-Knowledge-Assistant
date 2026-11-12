"""Traces (NFR-07): off by default, spans for requests and embedding, no text in attributes."""

from typing import cast

from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from eka.ports.embedder import Embedder
from eka.tracing import TracedEmbedder, build_provider


class _Embedder:
    model_name = "m"
    dimension = 3

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def embed_query(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.0, 0.0, 0.0] for _ in texts]


def test_off_without_endpoint() -> None:
    assert build_provider(None, 1.0) is None
    assert build_provider("", 1.0) is None


def test_embedding_spans_carry_sizes_not_text() -> None:
    exporter = InMemorySpanExporter()
    provider = build_provider(None, 1.0, exporter=exporter)
    assert provider is not None
    embedder = TracedEmbedder(cast(Embedder, _Embedder()), provider)

    assert embedder.embed_query("secret question text") == [0.1, 0.2, 0.3]
    embedder.embed_documents(["a", "b"])
    assert embedder.count_tokens("a b c") == 3

    spans = {s.name: s for s in exporter.get_finished_spans()}
    assert dict(spans["embed query"].attributes or {}) == {
        "eka.embedder.model": "m",
        "eka.embedder.chars": 20,
    }
    assert (spans["embed documents"].attributes or {})["eka.embedder.count"] == 2
    for span in spans.values():
        assert "secret" not in str(span.attributes)
    assert spans["embed query"].resource.attributes["service.name"] == "eka-core"


def test_zero_ratio_samples_nothing() -> None:
    exporter = InMemorySpanExporter()
    provider = build_provider(None, 0.0, exporter=exporter)
    assert provider is not None
    TracedEmbedder(cast(Embedder, _Embedder()), provider).embed_query("x")
    assert exporter.get_finished_spans() == ()


def test_sql_statements_become_spans() -> None:
    """Guards the skip_dep_check workaround: the instrumentation package pins SQLAlchemy < 2.1."""
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    from sqlalchemy import create_engine, text

    exporter = InMemorySpanExporter()
    provider = build_provider(None, 1.0, exporter=exporter)
    assert provider is not None
    engine = create_engine("sqlite://")
    instrumentor = SQLAlchemyInstrumentor()
    instrumentor.instrument(engine=engine, tracer_provider=provider, skip_dep_check=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("select 1"))
    finally:
        instrumentor.uninstrument()
    assert any("select" in s.name.lower() for s in exporter.get_finished_spans())
