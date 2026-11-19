# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""Retrieval metrics: Hit@k, mean reciprocal rank (MRR) and nDCG."""

import math
from collections.abc import Sequence
from dataclasses import dataclass

from eka.domain.models import SearchHit
from eka.eval.dataset import Question


@dataclass(frozen=True, slots=True)
class QuestionResult:
    question: Question
    rank: int | None  # 1-based rank of the first relevant passage, None if none was retrieved
    top_cosine: float | None  # best cosine among the passages the gate sees, None if none
    retrieved: tuple[str, ...]  # file names of the retrieved passages, in rank order
    # 1-based ranks of every relevant passage retrieved (for nDCG); empty when not recorded.
    relevant_ranks: tuple[int, ...] = ()
    latency_ms: float | None = None  # wall time of the search call, when measured


def is_relevant(hit: SearchHit, question: Question, *, any_document: bool = False) -> bool:
    """Right document and the expected text; with ``any_document`` the text alone decides (for a
    corpus whose files were merged into one)."""
    if not any_document and hit.filename != question.doc:
        return False
    return question.gold.lower() in hit.text.lower()


def first_relevant_rank(
    hits: Sequence[SearchHit], question: Question, *, any_document: bool = False
) -> int | None:
    for position, hit in enumerate(hits, start=1):
        if is_relevant(hit, question, any_document=any_document):
            return position
    return None


def hit_rate(results: Sequence[QuestionResult], k: int) -> float:
    """Share of questions with a relevant passage among the first ``k``."""
    if not results:
        return 0.0
    return sum(1 for r in results if r.rank is not None and r.rank <= k) / len(results)


def mean_reciprocal_rank(results: Sequence[QuestionResult]) -> float:
    if not results:
        return 0.0
    return sum(1.0 / r.rank for r in results if r.rank is not None) / len(results)


def ndcg(results: Sequence[QuestionResult], k: int = 10) -> float:
    """Mean binary-relevance nDCG@k over the retrieved list. The ideal ordering is the relevant
    passages that were retrieved, placed first; a relevant passage that was never retrieved is not
    counted, so with one relevant passage per question this is 1/log2(rank+1)."""
    if not results:
        return 0.0
    total = 0.0
    for r in results:
        found = r.relevant_ranks or (() if r.rank is None else (r.rank,))
        ranks = sorted(x for x in found if x <= k)
        if not ranks:
            continue
        dcg = sum(1.0 / math.log2(rank + 1) for rank in ranks)
        ideal = sum(1.0 / math.log2(i + 2) for i in range(len(ranks)))
        total += dcg / ideal
    return total / len(results)
