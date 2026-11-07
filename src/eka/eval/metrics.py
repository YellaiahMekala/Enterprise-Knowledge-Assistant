"""Retrieval metrics: Hit@k and mean reciprocal rank (MRR)."""

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
