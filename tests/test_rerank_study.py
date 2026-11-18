"""The reranking study: statistics helpers, per-question comparison, decision rule and report."""

import math

import pytest

from eka.eval.dataset import Question
from eka.eval.metrics import QuestionResult, ndcg
from eka.eval.rerank_study import (
    Comparison,
    Rule,
    bootstrap_ci,
    changed_cases,
    decide,
    percentile,
    render_study,
)


def result(qid: str, rank: int | None, kind: str = "lexical") -> QuestionResult:
    question = Question(qid, f"question {qid}?", "a.md", "x", kind)
    return QuestionResult(question, rank, 0.6, (), relevant_ranks=() if rank is None else (rank,))


def comparison(
    off_ranks: list[int | None],
    on_ranks: list[int | None],
    off_ms: list[float],
    on_ms: list[float],
    chunk_tokens: int = 256,
) -> Comparison:
    return Comparison(
        [result(f"q{i}", r) for i, r in enumerate(off_ranks)],
        [result(f"q{i}", r) for i, r in enumerate(on_ranks)],
        off_ms,
        on_ms,
        13,
        chunk_tokens,
        [0.4, 0.5, 0.6],
        [0.4, 0.5, 0.55],
    )


def test_percentile_interpolates_and_rejects_empty() -> None:
    assert percentile([10.0, 20.0, 30.0, 40.0], 50) == 25.0
    assert percentile([5.0], 95) == 5.0
    assert percentile([1.0, 2.0, 3.0, 4.0, 5.0], 100) == 5.0
    with pytest.raises(ValueError):
        percentile([], 50)


def test_bootstrap_interval_is_deterministic_and_brackets_the_mean() -> None:
    values = [1.0] * 30 + [0.0] * 10
    low, high = bootstrap_ci(values, resamples=2000)
    assert (low, high) == bootstrap_ci(values, resamples=2000)
    assert low < 0.75 < high
    assert bootstrap_ci([1.0] * 20, resamples=500) == (1.0, 1.0)
    assert bootstrap_ci([]) == (0.0, 0.0)


def test_ndcg_of_one_relevant_passage_is_the_discounted_rank() -> None:
    assert ndcg([result("a", 1)]) == pytest.approx(1.0)
    assert ndcg([result("a", 3)]) == pytest.approx(1 / math.log2(4))
    assert ndcg([result("a", None)]) == 0.0
    assert ndcg([]) == 0.0


def test_ndcg_with_two_relevant_passages_rewards_having_both_first() -> None:
    q = Question("q", "?", "a.md", "x", "lexical")
    first = QuestionResult(q, 1, 0.5, (), relevant_ranks=(1, 2))
    later = QuestionResult(q, 1, 0.5, (), relevant_ranks=(1, 4))
    assert ndcg([first]) == pytest.approx(1.0)
    assert ndcg([later]) < 1.0


def test_changed_cases_lists_better_and_worse_and_treats_a_miss_as_last() -> None:
    off = [result("a", 2), result("b", 1), result("c", None), result("d", 1)]
    on = [result("a", 1), result("b", 3), result("c", 5), result("d", 1)]
    improved, worsened = changed_cases(off, on)
    assert [row[0] for row in improved] == ["a", "c"]
    assert [row[0] for row in worsened] == ["b"]
    with pytest.raises(ValueError):
        changed_cases([result("a", 1)], [result("z", 1)])


def test_decision_passes_when_quality_holds_and_latency_is_low() -> None:
    c = comparison([2, 1, 1], [1, 1, 1], [20.0] * 5, [120.0] * 5)
    ok, lines = decide([c])
    assert ok
    assert all("PASS" in line for line in lines)


def test_decision_fails_on_latency_even_when_quality_improves() -> None:
    c = comparison([2, 1, 1], [1, 1, 1], [20.0] * 5, [700.0] * 5)
    ok, lines = decide([c])
    assert not ok
    assert sum("FAIL" in line for line in lines) == 2  # p95 limit and median added


def test_decision_fails_on_a_quality_regression_in_any_configuration() -> None:
    good = comparison([1, 1], [1, 1], [20.0], [60.0], chunk_tokens=256)
    bad = comparison([1, 1, 1, 1], [1, 3, 1, 1], [20.0], [60.0], chunk_tokens=64)
    ok, lines = decide([good, bad])
    assert not ok
    assert any("chunk 64" in line and "FAIL" in line for line in lines)
    assert not any("chunk 256" in line and "FAIL" in line for line in lines)


def test_rule_allows_a_small_documented_drop() -> None:
    c = comparison([1, 1, 1, 1], [1, 1, 1, 2], [20.0], [60.0])
    assert not decide([c])[0]
    lenient = Rule(max_worsened_over_improved=1, max_quality_drop=0.2)
    assert decide([c], lenient)[0]


def test_report_states_the_rule_the_intervals_and_the_verdict() -> None:
    c = comparison([2, 1, 1, 3], [1, 1, 1, 1], [20.0, 25.0, 30.0], [150.0, 160.0, 170.0])
    text = render_study([c], model="m", reranker="r", rerank_top=20, repeats=3, date="2026-11-18")
    assert "synthetic" in text
    assert "Decision rule (fixed before the run)" in text
    assert "Paired MRR change" in text
    assert "| Rerank on |" in text
    assert "2 better, 0 worse" in text.replace("Questions changed by reranking: ", "")
    assert "Result: rerank may be the default" in text
