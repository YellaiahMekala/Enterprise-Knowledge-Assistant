"""Markdown report for one evaluation run."""

import statistics
from collections.abc import Sequence
from dataclasses import dataclass

from eka.eval.metrics import QuestionResult, hit_rate, mean_reciprocal_rank

KS = (1, 3, 5)
THRESHOLDS = (0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75)


@dataclass(frozen=True, slots=True)
class RunInfo:
    model: str
    chunk_tokens: int
    chunk_overlap_tokens: int
    top_k: int
    documents: int
    chunks: int
    date: str


def _percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def _row(label: str, results: Sequence[QuestionResult]) -> str:
    cells = [_percent(hit_rate(results, k)) for k in KS]
    return (
        f"| {label} | {len(results)} | "
        + " | ".join(cells)
        + f" | {mean_reciprocal_rank(results):.3f} |"
    )


def render_report(
    info: RunInfo,
    results: Sequence[QuestionResult],
    challenge_cosines: Sequence[float],
) -> str:
    lines = [
        "# Retrieval evaluation",
        "",
        f"Run date {info.date}. Embedding model `{info.model}`, chunks of {info.chunk_tokens} "
        f"tokens with {info.chunk_overlap_tokens} overlap, top {info.top_k} passages per question. "
        f"Corpus: {info.documents} documents, {info.chunks} chunks.",
        "",
        "A passage is relevant when it comes from the expected document and contains the "
        "expected text.",
        "",
        "| Question set | Questions | Hit@1 | Hit@3 | Hit@5 | MRR |",
        "|---|---|---|---|---|---|",
        _row("All answerable", results),
    ]
    for kind in sorted({r.question.kind for r in results}):
        lines.append(_row(kind, [r for r in results if r.question.kind == kind]))

    answerable = [r.top_cosine for r in results if r.top_cosine is not None]
    lines += ["", "## Best-passage cosine similarity", ""]
    lines += ["| Set | Questions | Min | Median | Max |", "|---|---|---|---|---|"]
    if answerable:
        lines.append(_cosine_row("Answerable", answerable))
    if challenge_cosines:
        lines.append(_cosine_row("Unanswerable (challenge)", challenge_cosines))
    lines += [
        "",
        "The gap between the two rows is what a refusal threshold has to separate. "
        "Overlap between them means some wrong refusals or wrong answers at any threshold.",
    ]
    if answerable and challenge_cosines:
        lines += ["", "## Refusal threshold sweep", ""]
        lines += [
            "| Threshold | Answerable refused (wrong) | Unanswerable refused (right) |",
            "|---|---|---|",
        ]
        for threshold in THRESHOLDS:
            wrong = sum(1 for v in answerable if v < threshold) / len(answerable)
            right = sum(1 for v in challenge_cosines if v < threshold) / len(challenge_cosines)
            lines.append(f"| {threshold:.2f} | {_percent(wrong)} | {_percent(right)} |")

    misses = [r for r in results if r.rank is None or r.rank > 1]
    lines += ["", "## Questions without a relevant passage at rank 1", ""]
    if not misses:
        lines.append("None.")
    else:
        lines += [
            "| Id | Question | Expected | Rank | Retrieved (top 3) |",
            "|---|---|---|---|---|",
        ]
        for r in misses:
            rank = str(r.rank) if r.rank is not None else f"not in top {info.top_k}"
            lines.append(
                f"| {r.question.id} | {r.question.question} | {r.question.doc} | {rank} | "
                f"{', '.join(r.retrieved[:3])} |"
            )
    return "\n".join(lines) + "\n"


def _cosine_row(label: str, values: Sequence[float]) -> str:
    return (
        f"| {label} | {len(values)} | {min(values):.3f} | {statistics.median(values):.3f} | "
        f"{max(values):.3f} |"
    )
