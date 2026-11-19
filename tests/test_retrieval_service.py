# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""Retrieval logic against an in-memory search port."""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest

from eka.api.search import SearchResultOut
from eka.domain.models import SearchFilters, SearchHit
from eka.services.retrieval import (
    RetrievalService,
    RetrievalSettings,
    reciprocal_rank_fusion,
    sparse_query,
)
from tests.fakes import FakeEmbedder, InMemoryChunkSearch

EMBED = FakeEmbedder()


def vec(text: str) -> list[float]:
    return EMBED.embed_query(text)


def make_service(
    search: InMemoryChunkSearch, settings: RetrievalSettings | None = None
) -> RetrievalService:
    return RetrievalService(search, EMBED, settings or RetrievalSettings(candidates=10))


def test_a_chunk_found_by_both_paths_outranks_one_found_by_a_single_path() -> None:
    both, dense_only, sparse_only = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    fused = reciprocal_rank_fusion([[dense_only, both], [sparse_only, both]], k=60)
    assert fused[both] > fused[dense_only] and fused[both] > fused[sparse_only]


def test_rrf_uses_the_documented_formula() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    fused = reciprocal_rank_fusion([[a, b], [b]], k=60)
    assert fused[a] == pytest.approx(1 / 61)
    assert fused[b] == pytest.approx(1 / 62 + 1 / 61)


def test_rrf_depends_on_rank_not_on_the_original_scores() -> None:
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    once = reciprocal_rank_fusion([[a, b, c]], k=60)
    assert list(sorted(once, key=lambda k: -once[k])) == [a, b, c]


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("How many days?", "how | many | days"),
        ("Error E-4017 in ZIP code 90210!", "error | e | 4017 | in | zip | code | 90210"),
        ("'; DROP TABLE chunks;--", "drop | table | chunks"),
        ("a & b | !c :* (d)", "a | b | c | d"),
        ("???", ""),
        ("café naïve", "caf | na | ve"),
    ],
)
def test_query_terms_are_alphanumeric_or_joined(question: str, expected: str) -> None:
    assert sparse_query(question) == expected


def test_query_terms_are_capped() -> None:
    assert len(sparse_query(" ".join(f"w{i}" for i in range(100))).split(" | ")) == 32


@pytest.mark.anyio
async def test_hits_are_ranked_best_first_with_locator_and_filename() -> None:
    search = InMemoryChunkSearch()
    doc = uuid.uuid4()
    search.add_document("alice", doc, "leave.md")
    best = search.add_chunk(
        "alice", doc, "carry over five unused leave days", vec("carry over leave")
    )
    search.add_chunk("alice", doc, "the canteen opens at noon", vec("canteen noon"))
    hits = await make_service(search).search(
        "alice", "carry over unused leave", top_k=2, filters=SearchFilters()
    )
    assert hits[0].chunk_id == best and hits[0].rank == 1
    assert hits[0].filename == "leave.md" and hits[0].locator == {"type": "page", "page": 1}
    assert [h.rank for h in hits] == [1, 2]


@pytest.mark.anyio
async def test_every_hit_has_a_cosine_even_when_only_one_path_found_it() -> None:
    search = InMemoryChunkSearch()
    doc = uuid.uuid4()
    search.add_document("alice", doc, "a.txt")
    # Far in vector space but shares the question's words: only the sparse path finds it.
    far = search.add_chunk("alice", doc, "carry over leave", [0.0] * 383 + [1.0])
    search.add_chunk("alice", doc, "unrelated words", vec("zebra giraffe"))
    hits = await make_service(search, RetrievalSettings(candidates=1)).search(
        "alice", "carry over leave", top_k=5, filters=SearchFilters()
    )
    found = {h.chunk_id: h for h in hits}
    assert far in found
    # For unit vectors the cosine is the question's last coordinate.
    question = vec("carry over leave")
    assert found[far].cosine == pytest.approx(question[383], abs=1e-9)
    assert all(-1.0 <= h.cosine <= 1.0 for h in hits)


@pytest.mark.anyio
async def test_another_owners_chunks_are_never_returned() -> None:
    search = InMemoryChunkSearch()
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    search.add_document("alice", mine, "mine.txt")
    search.add_document("bob", theirs, "bob.txt")
    search.add_chunk("alice", mine, "leave policy for staff", vec("leave policy"))
    search.add_chunk("bob", theirs, "leave policy for contractors", vec("leave policy"))
    hits = await make_service(search).search(
        "alice", "leave policy", top_k=10, filters=SearchFilters()
    )
    assert hits and {h.filename for h in hits} == {"mine.txt"}


@pytest.mark.anyio
async def test_filters_narrow_the_search() -> None:
    search = InMemoryChunkSearch()
    old, new = uuid.uuid4(), uuid.uuid4()
    now = datetime(2026, 11, 1, tzinfo=UTC)
    search.add_document(
        "alice", old, "old.pdf", content_type="application/pdf", created_at=now - timedelta(days=30)
    )
    search.add_document("alice", new, "new.txt", content_type="text/plain", created_at=now)
    search.add_chunk("alice", old, "leave policy", vec("leave policy"))
    search.add_chunk("alice", new, "leave policy", vec("leave policy"))
    service = make_service(search)

    by_type = await service.search(
        "alice", "leave policy", top_k=5, filters=SearchFilters(content_types=("application/pdf",))
    )
    assert {h.filename for h in by_type} == {"old.pdf"}

    by_document = await service.search(
        "alice", "leave policy", top_k=5, filters=SearchFilters(document_ids=(new,))
    )
    assert {h.filename for h in by_document} == {"new.txt"}

    by_date = await service.search(
        "alice",
        "leave policy",
        top_k=5,
        filters=SearchFilters(uploaded_after=now - timedelta(days=1)),
    )
    assert {h.filename for h in by_date} == {"new.txt"}


@pytest.mark.anyio
async def test_a_filter_that_matches_nothing_returns_nothing_without_searching() -> None:
    search = InMemoryChunkSearch()
    doc = uuid.uuid4()
    search.add_document("alice", doc, "a.txt")
    search.add_chunk("alice", doc, "leave", vec("leave"))
    hits = await make_service(search).search(
        "alice", "leave", top_k=5, filters=SearchFilters(content_types=("application/pdf",))
    )
    assert hits == [] and search.exact_flags == []


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("chunks", "threshold", "expect_exact"), [(3, 10, True), (3, 2, False), (10, 10, True)]
)
async def test_small_owners_take_the_exact_path(
    chunks: int, threshold: int, expect_exact: bool
) -> None:
    search = InMemoryChunkSearch()
    doc = uuid.uuid4()
    search.add_document("alice", doc, "a.txt")
    for i in range(chunks):
        search.add_chunk("alice", doc, f"text {i}", vec(f"text {i}"))
    await make_service(search, RetrievalSettings(exact_max_chunks=threshold)).search(
        "alice", "text", top_k=2, filters=SearchFilters()
    )
    assert search.exact_flags == [expect_exact]


@pytest.mark.anyio
async def test_the_question_length_is_checked_here_too() -> None:
    service = make_service(InMemoryChunkSearch())
    with pytest.raises(ValueError):
        await service.search("alice", "", top_k=1, filters=SearchFilters())
    with pytest.raises(ValueError):
        await service.search("alice", "x" * 1001, top_k=1, filters=SearchFilters())


@pytest.mark.anyio
async def test_no_chunks_means_no_hits() -> None:
    assert (
        await make_service(InMemoryChunkSearch()).search(
            "alice", "anything", top_k=5, filters=SearchFilters()
        )
        == []
    )


class _CountingSearch(InMemoryChunkSearch):
    def __init__(self) -> None:
        super().__init__()
        self.dense_calls = 0
        self.sparse_calls = 0

    async def dense(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        self.dense_calls += 1
        return await super().dense(*args, **kwargs)

    async def sparse(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        self.sparse_calls += 1
        return await super().sparse(*args, **kwargs)


def _corpus() -> _CountingSearch:
    search = _CountingSearch()
    doc = uuid.uuid4()
    search.add_document("alice", doc, "leave.md")
    search.add_chunk("alice", doc, "carry over five unused leave days", vec("carry over leave"))
    return search


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("mode", "dense_calls", "sparse_calls"),
    [("hybrid", 1, 1), ("dense", 1, 0), ("sparse", 0, 1)],
)
async def test_mode_selects_which_paths_run(mode: str, dense_calls: int, sparse_calls: int) -> None:
    search = _corpus()
    service = make_service(search, RetrievalSettings(candidates=10, mode=mode))  # type: ignore[arg-type]

    hits = await service.search("alice", "carry over leave", top_k=3, filters=SearchFilters())

    assert (search.dense_calls, search.sparse_calls) == (dense_calls, sparse_calls)
    assert hits, "every mode still returns the matching chunk, with a cosine for the gate"
    assert hits[0].cosine is not None


class _KeywordReranker:
    """Scores a passage by how many times a marker word appears, so the order is predictable."""

    model_name = "test-reranker"

    def __init__(self, marker: str) -> None:
        self._marker = marker
        self.calls: list[list[str]] = []

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        self.calls.append(list(passages))
        return [float(p.count(self._marker)) for p in passages]


def _three_leave_chunks() -> InMemoryChunkSearch:
    search = InMemoryChunkSearch()
    doc = uuid.uuid4()
    search.add_document("alice", doc, "leave.md")
    for text in ("leave rules apply", "leave leave leave days", "leave days carry over"):
        search.add_chunk("alice", doc, text, vec("carry over leave"))
    return search


@pytest.mark.anyio
async def test_a_reranker_reorders_the_head_of_the_fused_list() -> None:
    reranker = _KeywordReranker("leave")
    service = RetrievalService(
        _three_leave_chunks(), EMBED, RetrievalSettings(candidates=10), reranker
    )

    hits = await service.search("alice", "carry over leave", top_k=3, filters=SearchFilters())

    assert hits[0].text == "leave leave leave days"
    assert [h.rank for h in hits] == [1, 2, 3]
    assert len(reranker.calls) == 1 and len(reranker.calls[0]) == 3


@pytest.mark.anyio
async def test_only_rerank_top_candidates_are_rescored() -> None:
    reranker = _KeywordReranker("leave")
    service = RetrievalService(
        _three_leave_chunks(), EMBED, RetrievalSettings(candidates=10, rerank_top=2), reranker
    )

    hits = await service.search("alice", "carry over leave", top_k=3, filters=SearchFilters())

    assert len(reranker.calls[0]) == 2
    assert len(hits) == 3


@pytest.mark.anyio
async def test_without_a_reranker_the_order_is_the_fused_order() -> None:
    search = _three_leave_chunks()
    plain = await make_service(search).search(
        "alice", "carry over leave", top_k=3, filters=SearchFilters()
    )
    ranked = await RetrievalService(search, EMBED, RetrievalSettings(candidates=10), None).search(
        "alice", "carry over leave", top_k=3, filters=SearchFilters()
    )
    assert [h.chunk_id for h in plain] == [h.chunk_id for h in ranked]


@pytest.mark.anyio
async def test_hits_carry_the_rerank_score_only_when_a_reranker_ran() -> None:
    search = _three_leave_chunks()
    reranked = await RetrievalService(
        search, EMBED, RetrievalSettings(candidates=10), _KeywordReranker("leave")
    ).search("alice", "carry over leave", top_k=3, filters=SearchFilters())
    assert [h.rerank for h in reranked] == [3.0, 1.0, 1.0]

    plain = await make_service(search).search(
        "alice", "carry over leave", top_k=3, filters=SearchFilters()
    )
    assert all(h.rerank is None for h in plain)


def test_the_search_response_exposes_the_rerank_score() -> None:
    base = dict(
        rank=1,
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        filename="a.md",
        locator={},
        text="t",
        fused=0.03,
        cosine=0.7,
    )
    assert SearchResultOut.from_hit(SearchHit(**base, rerank=4.25)).scores.rerank == 4.25  # type: ignore[arg-type]
    assert SearchResultOut.from_hit(SearchHit(**base)).scores.rerank is None  # type: ignore[arg-type]
