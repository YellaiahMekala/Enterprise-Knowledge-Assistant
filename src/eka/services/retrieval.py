# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""Hybrid retrieval: dense and full-text candidates fused by reciprocal rank (TDD 4.6)."""

import asyncio
import re
from collections.abc import Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from eka.domain.models import Candidate, Role, SearchFilters, SearchHit
from eka.ports.embedder import Embedder
from eka.ports.reranker import Reranker
from eka.ports.search import ChunkSearch

MAX_QUERY_CHARS = 1000
MAX_QUERY_TERMS = 32
_TERM = re.compile(r"[A-Za-z0-9]+")

EmbedderProvider = Callable[[], Awaitable[Embedder]]


def sparse_query(question: str) -> str:
    """A ``to_tsquery`` expression OR-ing the question's alphanumeric terms.

    OR, because AND over a full question matches almost nothing. Only ``[A-Za-z0-9]`` is kept, so
    user text cannot inject tsquery syntax."""
    terms = _TERM.findall(question.lower())[:MAX_QUERY_TERMS]
    return " | ".join(terms)


def reciprocal_rank_fusion(rankings: Sequence[Sequence[UUID]], *, k: int) -> dict[UUID, float]:
    """Sum ``1 / (k + rank)`` per chunk over all rankings. Ranks start at 1."""
    scores: dict[UUID, float] = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return scores


@dataclass(frozen=True, slots=True)
class RetrievalSettings:
    candidates: int = 30
    rrf_k: int = 60
    exact_max_chunks: int = 20_000
    ef_search: int = 400
    # "dense" and "sparse" exist for the E2 experiment; production uses "hybrid".
    mode: Literal["hybrid", "dense", "sparse"] = "hybrid"
    # With a reranker, this many top fused candidates are re-scored and re-ordered (experiment E3).
    rerank_top: int = 20


class RetrievalService:
    def __init__(
        self,
        search: ChunkSearch,
        embedder: Embedder,
        settings: RetrievalSettings,
        reranker: Reranker | None = None,
    ) -> None:
        self._search = search
        self._embedder = embedder
        self._settings = settings
        self._reranker = reranker

    async def search(
        self,
        owner_id: str,
        question: str,
        *,
        top_k: int,
        filters: SearchFilters,
    ) -> list[SearchHit]:
        if not 1 <= len(question) <= MAX_QUERY_CHARS:
            raise ValueError("question length out of range")
        document_ids = await self._search.resolve_documents(owner_id, filters)
        if document_ids is not None and not document_ids:
            return []

        vector = await asyncio.to_thread(self._embedder.embed_query, question)
        exact = await self._search.count_chunks(owner_id) <= self._settings.exact_max_chunks
        dense: list[Candidate] = []
        if self._settings.mode != "sparse":
            dense = await self._search.dense(
                owner_id,
                vector,
                self._settings.candidates,
                document_ids=document_ids,
                exact=exact,
                ef_search=self._settings.ef_search,
            )
            # The approximate path returns rows in relaxed order.
            dense.sort(key=lambda candidate: candidate.score)

        terms = sparse_query(question)
        sparse: list[Candidate] = []
        if terms and self._settings.mode != "dense":
            sparse = await self._search.sparse(
                owner_id, terms, self._settings.candidates, document_ids=document_ids
            )

        fused = reciprocal_rank_fusion(
            [[c.chunk_id for c in dense], [c.chunk_id for c in sparse]],
            k=self._settings.rrf_k,
        )
        by_id = {candidate.chunk_id: candidate for candidate in (*dense, *sparse)}
        ordered = sorted(fused, key=lambda chunk_id: -fused[chunk_id])
        rerank_scores: dict[UUID, float] = {}
        if self._reranker is not None and ordered:
            ordered, rerank_scores = await self._rerank(question, ordered, by_id)
        best = ordered[:top_k]

        similarity = {c.chunk_id: 1.0 - c.score for c in dense}
        missing = [chunk_id for chunk_id in best if chunk_id not in similarity]
        if missing:
            similarity.update(await self._search.cosine(owner_id, vector, missing))

        document_ids_in_hits = list({by_id[chunk_id].document_id for chunk_id in best})
        info = await self._search.document_info(owner_id, document_ids_in_hits)
        hits: list[SearchHit] = []
        for chunk_id in best:
            candidate = by_id[chunk_id]
            document = info.get(candidate.document_id)
            if document is None or chunk_id not in similarity:
                continue
            hits.append(
                SearchHit(
                    rank=len(hits) + 1,
                    chunk_id=chunk_id,
                    document_id=candidate.document_id,
                    filename=document.filename,
                    locator=candidate.locator,
                    text=candidate.text,
                    fused=fused[chunk_id],
                    cosine=similarity[chunk_id],
                    source_url=document.source_url,
                    fetched_at=document.fetched_at,
                    rerank=rerank_scores.get(chunk_id),
                )
            )
        return hits

    async def _rerank(
        self, question: str, ordered: list[UUID], by_id: dict[UUID, Candidate]
    ) -> tuple[list[UUID], dict[UUID, float]]:
        """Re-order the head of the fused list by cross-encoder score. The tail keeps its order.
        ``fused`` stays the RRF score, so the answer step and the refusal gate are unaffected."""
        assert self._reranker is not None
        head = ordered[: self._settings.rerank_top]
        scores = await asyncio.to_thread(
            self._reranker.score, question, [by_id[chunk_id].text for chunk_id in head]
        )
        by_score = sorted(zip(scores, head, strict=True), key=lambda p: -p[0])
        reranked = [chunk_id for _, chunk_id in by_score]
        return reranked + ordered[len(head) :], {chunk_id: score for score, chunk_id in by_score}


RetrievalServiceFactory = Callable[
    [str, Role, Embedder], AbstractAsyncContextManager[RetrievalService]
]
