"""Regression gate: compare a run with the minimum scores kept in ``eval/thresholds.json``."""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from eka.eval.metrics import QuestionResult, hit_rate, mean_reciprocal_rank


@dataclass(frozen=True, slots=True)
class Thresholds:
    min_hit_at_3: float
    min_mrr: float
    # Share of answerable questions the refusal gate may wrongly refuse at ``gate_cosine``.
    max_wrong_refusals: float
    gate_cosine: float


def load_thresholds(path: Path) -> Thresholds:
    data = json.loads(path.read_text(encoding="utf-8"))
    return Thresholds(
        min_hit_at_3=float(data["min_hit_at_3"]),
        min_mrr=float(data["min_mrr"]),
        max_wrong_refusals=float(data["max_wrong_refusals"]),
        gate_cosine=float(data["gate_cosine"]),
    )


def check(results: Sequence[QuestionResult], thresholds: Thresholds) -> list[str]:
    """Human-readable failures; empty when the run meets every threshold."""
    failures = []
    hit3 = hit_rate(results, 3)
    if hit3 < thresholds.min_hit_at_3:
        failures.append(f"Hit@3 {hit3:.3f} is below the minimum {thresholds.min_hit_at_3:.3f}")
    mrr = mean_reciprocal_rank(results)
    if mrr < thresholds.min_mrr:
        failures.append(f"MRR {mrr:.3f} is below the minimum {thresholds.min_mrr:.3f}")
    refused = [r for r in results if r.top_cosine is None or r.top_cosine < thresholds.gate_cosine]
    wrong = len(refused) / len(results) if results else 0.0
    if wrong > thresholds.max_wrong_refusals:
        failures.append(
            f"{wrong:.1%} of answerable questions fall below the refusal gate "
            f"{thresholds.gate_cosine:.2f}; the maximum is {thresholds.max_wrong_refusals:.1%}"
        )
    return failures
