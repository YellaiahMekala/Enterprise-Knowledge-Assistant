# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""Reranking study (D1.2.5): the same questions with the cross-encoder off and on, with confidence
intervals, a per-question comparison and search latency. Free to run: local embedder and local
cross-encoder, no language model, no network after the models are cached.

    python -m eka.eval.rerank_study --database-url "$EKA_DATABASE_URL" \
        --out eval/reports/e3_rerank_study.md

The decision rule is fixed in code (``Rule``) before any number is looked at; ``decide`` applies it.
"""

import argparse
import asyncio
import math
import os
import random
import statistics
import sys
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from eka.adapters.db.engine import Database
from eka.adapters.embedder_fastembed import FastEmbedEmbedder
from eka.adapters.reranker_fastembed import FastEmbedReranker
from eka.eval.dataset import Question, load_challenge, load_questions
from eka.eval.metrics import QuestionResult, hit_rate, mean_reciprocal_rank, ndcg
from eka.eval.runner import (
    EvalConfig,
    challenge_cosines,
    delete_corpus,
    ingest_corpus,
    run_questions,
)

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RERANKER = "Xenova/ms-marco-MiniLM-L-6-v2"
BOOTSTRAP_RESAMPLES = 10_000
SEED = 20261118


@dataclass(frozen=True, slots=True)
class Rule:
    """Reranking becomes the default only if every line holds in every configuration."""

    max_quality_drop: float = 0.01  # MRR and Hit@3 with rerank may be at most this far below off
    max_worsened_over_improved: int = 0  # questions that got worse minus questions that improved
    max_p95_ms: float = 500.0  # search latency with rerank, half of the 1 s search SLO
    max_added_p50_ms: float = 250.0  # median added by the cross-encoder


RULE = Rule()


def percentile(values: Sequence[float], q: float) -> float:
    """Linear-interpolated percentile, q in [0, 100]."""
    if not values:
        raise ValueError("no values")
    ordered = sorted(values)
    position = (len(ordered) - 1) * q / 100
    low = math.floor(position)
    high = math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def bootstrap_ci(
    values: Sequence[float], *, resamples: int = BOOTSTRAP_RESAMPLES, seed: int = SEED
) -> tuple[float, float]:
    """95% percentile bootstrap interval for the mean."""
    if not values:
        return (0.0, 0.0)
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(resamples))
    return means[int(0.025 * resamples)], means[int(0.975 * resamples) - 1]


def per_question(results: Sequence[QuestionResult], metric: str) -> list[float]:
    """One value per question for ``hit1``, ``hit3``, ``hit5``, ``mrr`` or ``ndcg``."""
    funcs: dict[str, Callable[[QuestionResult], float]] = {
        "hit1": lambda r: hit_rate([r], 1),
        "hit3": lambda r: hit_rate([r], 3),
        "hit5": lambda r: hit_rate([r], 5),
        "mrr": lambda r: mean_reciprocal_rank([r]),
        "ndcg": lambda r: ndcg([r]),
    }
    return [funcs[metric](r) for r in results]


@dataclass(frozen=True, slots=True)
class Comparison:
    off: list[QuestionResult]
    on: list[QuestionResult]
    off_ms: list[float]  # pooled latencies over the timed repeats
    on_ms: list[float]
    chunks: int
    chunk_tokens: int
    off_gate: list[float]  # best cosine of unanswerable questions
    on_gate: list[float]


def _rank_key(r: QuestionResult) -> float:
    return math.inf if r.rank is None else float(r.rank)


def changed_cases(
    off: Sequence[QuestionResult], on: Sequence[QuestionResult]
) -> tuple[list[tuple[str, str, float, float]], list[tuple[str, str, float, float]]]:
    """(improved, worsened) as (id, question, rank off, rank on); a missing rank is infinity."""
    improved, worsened = [], []
    for a, b in zip(off, on, strict=True):
        if a.question.id != b.question.id:
            raise ValueError("result lists are not aligned")
        row = (a.question.id, a.question.question, _rank_key(a), _rank_key(b))
        if _rank_key(b) < _rank_key(a):
            improved.append(row)
        elif _rank_key(b) > _rank_key(a):
            worsened.append(row)
    return improved, worsened


def decide(comparisons: Sequence[Comparison], rule: Rule = RULE) -> tuple[bool, list[str]]:
    """Apply the rule. Returns (rerank may be the default, one line per check)."""
    lines: list[str] = []
    ok = True
    for c in comparisons:
        tag = f"chunk {c.chunk_tokens} tokens ({c.chunks} chunks)"
        d_mrr = mean_reciprocal_rank(c.on) - mean_reciprocal_rank(c.off)
        d_h3 = hit_rate(c.on, 3) - hit_rate(c.off, 3)
        improved, worsened = changed_cases(c.off, c.on)
        p95 = percentile(c.on_ms, 95)
        added_p50 = percentile(c.on_ms, 50) - percentile(c.off_ms, 50)
        checks = [
            (
                d_mrr >= -rule.max_quality_drop,
                f"MRR change {d_mrr:+.3f} (floor -{rule.max_quality_drop})",
            ),
            (
                d_h3 >= -rule.max_quality_drop,
                f"Hit@3 change {d_h3:+.3f} (floor -{rule.max_quality_drop})",
            ),
            (
                len(worsened) - len(improved) <= rule.max_worsened_over_improved,
                f"worsened {len(worsened)} vs improved {len(improved)}",
            ),
            (p95 <= rule.max_p95_ms, f"p95 with rerank {p95:.0f} ms (limit {rule.max_p95_ms:.0f})"),
            (
                added_p50 <= rule.max_added_p50_ms,
                f"median added {added_p50:.0f} ms (limit {rule.max_added_p50_ms:.0f})",
            ),
        ]
        for passed, text in checks:
            ok = ok and passed
            lines.append(f"- {tag}: {'PASS' if passed else 'FAIL'}, {text}")
    return ok, lines


def _pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def _ci_cell(values: list[float], *, percent: bool) -> str:
    mean = sum(values) / len(values) if values else 0.0
    low, high = bootstrap_ci(values)
    if percent:
        return f"{_pct(mean)} ({_pct(low)} to {_pct(high)})"
    return f"{mean:.3f} ({low:.3f} to {high:.3f})"


def render_study(
    comparisons: Sequence[Comparison],
    *,
    model: str,
    reranker: str,
    rerank_top: int,
    repeats: int,
    date: str,
    rule: Rule = RULE,
) -> str:
    ok, verdict_lines = decide(comparisons, rule)
    lines = [
        "# Reranking study (D1.2.5)",
        "",
        f"Run date {date}. Embedding model `{model}`, cross-encoder `{reranker}`, top {rerank_top} "
        f"fused candidates re-scored, top 10 returned. No language model, no network.",
        "",
        "Questions are author-written and **synthetic**: the first 44 are the original set, the "
        "rest (ids q45 and up, and challenge c11 to c24) were added for this study with "
        "overlapping vocabulary, indirect phrasing and near-miss negatives. One author, one "
        "corpus of 13 short files: intervals show sampling noise over these questions, not "
        "uncertainty about other corpora.",
        "",
        "Intervals are 95% percentile bootstrap over questions "
        f"({BOOTSTRAP_RESAMPLES} resamples, seed {SEED}). Hit@k equals recall@k here, because "
        "each question has one labelled source passage. nDCG@10 is binary-relevance over the "
        f"retrieved list. Latency is the whole search call (query embedding, both candidate "
        f"queries, fusion, rerank) as the API runs it, pooled over {repeats} timed passes after "
        "one untimed warm-up pass, model already loaded.",
        "",
        "## Decision rule (fixed before the run)",
        "",
        "Rerank on becomes the default only if, in every configuration below: MRR and Hit@3 are "
        f"each at most {rule.max_quality_drop} lower than with rerank off; no more questions get "
        "worse than get better; p95 search latency with rerank is at most "
        f"{rule.max_p95_ms:.0f} ms; and the median latency added is at most "
        f"{rule.max_added_p50_ms:.0f} ms.",
    ]
    for c in comparisons:
        n = len(c.off)
        lines += [
            "",
            f"## Chunks of {c.chunk_tokens} tokens ({c.chunks} chunks, {n} answerable questions)",
            "",
            "| Metric | Rerank off | Rerank on |",
            "|---|---|---|",
        ]
        for label, key, percent in (
            ("Hit@1 (recall@1)", "hit1", True),
            ("Hit@3 (recall@3)", "hit3", True),
            ("Hit@5 (recall@5)", "hit5", True),
            ("MRR", "mrr", False),
            ("nDCG@10", "ndcg", False),
        ):
            lines.append(
                f"| {label} | {_ci_cell(per_question(c.off, key), percent=percent)} | "
                f"{_ci_cell(per_question(c.on, key), percent=percent)} |"
            )
        diffs = [
            b - a
            for a, b in zip(per_question(c.off, "mrr"), per_question(c.on, "mrr"), strict=True)
        ]
        low, high = bootstrap_ci(diffs)
        lines += [
            "",
            f"Paired MRR change (on minus off): {sum(diffs) / n:+.3f}, 95% interval "
            f"{low:+.3f} to {high:+.3f}.",
            "",
            "| Latency (ms) | p50 | p95 | mean |",
            "|---|---|---|---|",
        ]
        for label, values in (("Rerank off", c.off_ms), ("Rerank on", c.on_ms)):
            lines.append(
                f"| {label} | {percentile(values, 50):.0f} | {percentile(values, 95):.0f} | "
                f"{statistics.fmean(values):.0f} |"
            )
        improved, worsened = changed_cases(c.off, c.on)
        lines += [
            "",
            f"Questions changed by reranking: {len(improved)} better, {len(worsened)} worse.",
        ]
        if improved or worsened:
            lines += [
                "",
                "| Id | Direction | Question | Rank off | Rank on |",
                "|---|---|---|---|---|",
            ]
            for direction, rows in (("better", improved), ("worse", worsened)):
                for qid, text, a, b in rows:
                    fa = "none" if math.isinf(a) else str(int(a))
                    fb = "none" if math.isinf(b) else str(int(b))
                    lines.append(f"| {qid} | {direction} | {text} | {fa} | {fb} |")
        kinds = sorted({r.question.kind for r in c.off})
        lines += ["", "| Kind | Questions | MRR off | MRR on |", "|---|---|---|---|"]
        for kind in kinds:
            of_kind_off = [r for r in c.off if r.question.kind == kind]
            of_kind_on = [r for r in c.on if r.question.kind == kind]
            mrr_off = mean_reciprocal_rank(of_kind_off)
            mrr_on = mean_reciprocal_rank(of_kind_on)
            lines.append(f"| {kind} | {len(of_kind_off)} | {mrr_off:.3f} | {mrr_on:.3f} |")
        lines += [
            "",
            f"Unanswerable questions ({len(c.off_gate)}): best-passage cosine median "
            f"{statistics.median(c.off_gate):.3f} off, {statistics.median(c.on_gate):.3f} on; at "
            f"the 0.50 gate, {sum(v >= 0.5 for v in c.off_gate)} off and "
            f"{sum(v >= 0.5 for v in c.on_gate)} on would reach the model. The gate uses the dense "
            "cosine, which reranking does not change, but it can change which passages are in the "
            "top five.",
        ]
    lines += [
        "",
        "## Verdict",
        "",
        *verdict_lines,
        "",
        f"Result: rerank {'may' if ok else 'may NOT'} be the default under the rule above.",
    ]
    return "\n".join(lines) + "\n"


async def _timed_passes(
    database: Database,
    owner: str,
    embedder: FastEmbedEmbedder,
    config: EvalConfig,
    questions: list[Question],
    repeats: int,
) -> tuple[list[QuestionResult], list[float]]:
    await run_questions(database, owner, embedder, config, questions)  # untimed warm-up
    latencies: list[float] = []
    results: list[QuestionResult] = []
    for _ in range(repeats):
        results = await run_questions(database, owner, embedder, config, questions)
        latencies += [r.latency_ms for r in results if r.latency_ms is not None]
    return results, latencies


async def _study(args: argparse.Namespace) -> list[Comparison]:
    embedder = FastEmbedEmbedder(args.model, args.model_cache, 384)
    reranker = FastEmbedReranker(args.reranker, args.model_cache)
    questions = load_questions(args.questions)
    challenge = load_challenge(args.challenge)
    comparisons = []
    database = Database(args.database_url)
    try:
        for chunk_tokens in args.chunk_tokens:
            base = EvalConfig(chunk_tokens=chunk_tokens, chunk_overlap_tokens=args.overlap)
            with_rerank = replace(base, reranker=reranker)
            owner = f"eval-{uuid.uuid4().hex[:8]}"
            try:
                summary = await ingest_corpus(database, owner, args.corpus, embedder, base)
                off, off_ms = await _timed_passes(
                    database, owner, embedder, base, questions, args.repeats
                )
                on, on_ms = await _timed_passes(
                    database, owner, embedder, with_rerank, questions, args.repeats
                )
                off_gate = await challenge_cosines(database, owner, embedder, base, challenge)
                on_gate = await challenge_cosines(database, owner, embedder, with_rerank, challenge)
            finally:
                await delete_corpus(database, owner)
            comparisons.append(
                Comparison(off, on, off_ms, on_ms, summary.chunks, chunk_tokens, off_gate, on_gate)
            )
    finally:
        await database.dispose()
    return comparisons


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m eka.eval.rerank_study", description=__doc__)
    parser.add_argument("--database-url", default=os.environ.get("EKA_DATABASE_URL"))
    parser.add_argument("--corpus", type=Path, default=ROOT / "eval" / "corpus")
    parser.add_argument("--questions", type=Path, default=ROOT / "eval" / "questions.jsonl")
    parser.add_argument("--challenge", type=Path, default=ROOT / "eval" / "challenge.jsonl")
    parser.add_argument("--model", default="BAAI/bge-small-en-v1.5")
    parser.add_argument("--reranker", default=DEFAULT_RERANKER)
    parser.add_argument("--model-cache", type=Path, default=ROOT / "data" / "models")
    parser.add_argument("--chunk-tokens", type=int, nargs="+", default=[256, 64])
    parser.add_argument("--overlap", type=int, default=16)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument(
        "--out", type=Path, default=ROOT / "eval" / "reports" / "e3_rerank_study.md"
    )
    args = parser.parse_args()
    if not args.database_url:
        print("Set --database-url or EKA_DATABASE_URL.", file=sys.stderr)
        return 2
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        comparisons = runner.run(_study(args))
    report = render_study(
        comparisons,
        model=args.model,
        reranker=args.reranker,
        rerank_top=EvalConfig().retrieval.rerank_top,
        repeats=args.repeats,
        date=datetime.now(UTC).date().isoformat(),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
