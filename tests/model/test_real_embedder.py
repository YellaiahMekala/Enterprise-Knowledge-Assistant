"""The real embedding model (spike S-3 turned into a test). Opt-in: it needs the model files
(about 200 MB, downloaded once into ``EKA_EMBEDDING_CACHE_DIR``, default ``data/models``).

    EKA_TEST_REAL_MODEL=1 pytest tests/model
"""

import math
import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from eka.domain.models import Segment
from eka.ingestion.chunking import chunk_segment

if TYPE_CHECKING:
    from eka.adapters.embedder_fastembed import FastEmbedEmbedder

pytestmark = [
    pytest.mark.model,
    pytest.mark.skipif(
        os.environ.get("EKA_TEST_REAL_MODEL") != "1",
        reason="set EKA_TEST_REAL_MODEL=1 to load the real embedding model",
    ),
]

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def embedder() -> "FastEmbedEmbedder":
    from eka.adapters.embedder_fastembed import FastEmbedEmbedder

    cache = Path(os.environ.get("EKA_TEST_MODEL_CACHE", ROOT / "data" / "models"))
    return FastEmbedEmbedder("BAAI/bge-small-en-v1.5", cache, 384)


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def test_vectors_have_the_column_dimension_and_unit_length(embedder: "FastEmbedEmbedder") -> None:
    vectors = embedder.embed_documents(["Up to five unused days carry over.", "Book travel early."])
    assert [len(v) for v in vectors] == [384, 384]
    for vector in vectors:
        assert math.isclose(math.sqrt(sum(x * x for x in vector)), 1.0, abs_tol=1e-3)


def test_a_related_passage_scores_higher_than_an_unrelated_one(
    embedder: "FastEmbedEmbedder",
) -> None:
    query = embedder.embed_query("How many leave days can I carry over?")
    related, unrelated = embedder.embed_documents(
        ["Employees may carry over up to five unused leave days.", "The canteen opens at noon."]
    )
    assert cosine(query, related) > cosine(query, unrelated)


def test_token_counts_come_from_the_models_own_tokenizer(embedder: "FastEmbedEmbedder") -> None:
    assert embedder.count_tokens("Hello world, this is a test.") == 8  # recorded in spike S-3
    assert embedder.count_tokens("") == 0


def test_a_wrong_expected_dimension_fails_at_start_up() -> None:
    from eka.adapters.embedder_fastembed import FastEmbedEmbedder

    cache = Path(os.environ.get("EKA_TEST_MODEL_CACHE", ROOT / "data" / "models"))
    with pytest.raises(RuntimeError, match="dimensions"):
        FastEmbedEmbedder("BAAI/bge-small-en-v1.5", cache, 768)


def test_chunks_measured_by_the_real_tokenizer_never_exceed_the_limit(
    embedder: "FastEmbedEmbedder",
) -> None:
    text = " ".join(
        f"Clause {i}: the employer reimburses travel costs within 30 days (ref. HR-{i:04d})."
        for i in range(200)
    )
    chunks = chunk_segment(
        Segment(text, {"type": "page", "page": 1}),
        embedder.count_tokens,
        max_tokens=256,
        overlap_tokens=32,
    )
    assert len(chunks) > 3
    assert all(c.token_count == embedder.count_tokens(c.text) <= 256 for c in chunks)
