"""The evaluation harness: question files, metrics and the report."""

import uuid
from collections.abc import Sequence
from pathlib import Path

import pytest

from eka.domain.models import SearchHit
from eka.eval.dataset import Question, load_challenge, load_questions
from eka.eval.gate import Thresholds, check, load_thresholds
from eka.eval.metrics import (
    QuestionResult,
    first_relevant_rank,
    hit_rate,
    is_relevant,
    mean_reciprocal_rank,
)
from eka.eval.report import RunInfo, render_report

EVAL_DIR = Path(__file__).resolve().parents[1] / "eval"


def hit(filename: str, text: str) -> SearchHit:
    return SearchHit(
        rank=1,
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        filename=filename,
        locator={},
        text=text,
        fused=0.1,
        cosine=0.5,
    )


QUESTION = Question("q1", "How long?", "a.md", "7 years", "lexical")


def test_a_passage_must_come_from_the_right_document_and_contain_the_gold_text() -> None:
    assert is_relevant(hit("a.md", "Records are kept for 7 YEARS."), QUESTION)
    assert not is_relevant(hit("b.md", "Records are kept for 7 years."), QUESTION)
    assert not is_relevant(hit("a.md", "Records are kept for 5 years."), QUESTION)


def test_rank_is_the_position_of_the_first_relevant_passage() -> None:
    hits = [hit("a.md", "nothing"), hit("b.md", "7 years"), hit("a.md", "7 years")]
    assert first_relevant_rank(hits, QUESTION) == 3
    assert first_relevant_rank(hits[:2], QUESTION) is None


def _result(rank: int | None) -> QuestionResult:
    return QuestionResult(QUESTION, rank, 0.5, ())


def test_hit_rate_and_mrr() -> None:
    results = [_result(1), _result(2), _result(None), _result(4)]
    assert hit_rate(results, 1) == 0.25
    assert hit_rate(results, 3) == 0.5
    assert hit_rate(results, 5) == 0.75
    assert mean_reciprocal_rank(results) == pytest.approx((1 + 0.5 + 0 + 0.25) / 4)


def test_metrics_of_nothing_are_zero() -> None:
    assert hit_rate([], 3) == 0.0
    assert mean_reciprocal_rank([]) == 0.0


def test_the_report_lists_misses_and_both_cosine_rows() -> None:
    info = RunInfo("model-x", 256, 32, 10, documents=2, chunks=5, date="2026-01-01")
    results = [
        QuestionResult(QUESTION, 1, 0.8, ("a.md",)),
        QuestionResult(Question("q2", "Why?", "b.md", "x", "paraphrase"), 3, 0.6, ("c.md", "b.md")),
    ]
    text = render_report(info, results, [0.4, 0.5])
    assert "model-x" in text and "2 documents, 5 chunks" in text
    assert "| All answerable | 2 | 50.0% |" in text
    assert "| paraphrase | 1 |" in text
    assert "Unanswerable (challenge)" in text
    assert "| q2 | Why? | b.md | 3 |" in text
    assert "| q1 |" not in text  # rank 1 is not a miss


# --- the shipped files ----------------------------------------------------------------------


def test_every_shipped_question_points_at_a_real_document_and_a_real_phrase() -> None:
    questions = load_questions(EVAL_DIR / "questions.jsonl")
    assert len(questions) >= 40
    for q in questions:
        source = (EVAL_DIR / "corpus" / q.doc).read_text(encoding="utf-8")
        assert q.gold.lower() in source.lower(), f"{q.id}: gold text not in {q.doc}"
        assert q.kind in {"lexical", "paraphrase", "exact", "hard"}, q.id


def test_the_challenge_set_is_present_and_has_unique_ids() -> None:
    challenge = load_challenge(EVAL_DIR / "challenge.jsonl")
    assert len(challenge) >= 10
    assert len({c.id for c in challenge}) == len(challenge)


def test_duplicate_question_ids_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "q.jsonl"
    row = '{"id": "q1", "question": "a", "doc": "d", "gold": "g"}\n'
    path.write_text(row + row, encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        load_questions(path)


def test_invalid_json_names_the_file_and_line(tmp_path: Path) -> None:
    path = tmp_path / "q.jsonl"
    path.write_text('{"id": "q1"}\nnot json\n', encoding="utf-8")
    with pytest.raises(ValueError, match=r"q\.jsonl:2"):
        load_challenge(path)


# --- the regression gate ---------------------------------------------------------------------


def _results(ranks: Sequence[int | None], cosine: float = 0.8) -> list[QuestionResult]:
    return [QuestionResult(QUESTION, rank, cosine, ()) for rank in ranks]


THRESHOLDS = Thresholds(min_hit_at_3=0.9, min_mrr=0.8, max_wrong_refusals=0.1, gate_cosine=0.55)


def test_a_good_run_passes_the_gate() -> None:
    assert check(_results([1] * 9 + [2]), THRESHOLDS) == []


def test_a_low_hit_rate_fails_the_gate() -> None:
    failures = check(_results([1] * 5 + [None] * 5), THRESHOLDS)
    assert any(f.startswith("Hit@3 0.500") for f in failures)


def test_a_low_mrr_fails_the_gate() -> None:
    failures = check(_results([3] * 10), THRESHOLDS)  # Hit@3 is 100% but MRR is 0.333
    assert len(failures) == 1 and failures[0].startswith("MRR 0.333")


def test_too_many_questions_below_the_refusal_gate_fail_it() -> None:
    failures = check(_results([1] * 10, cosine=0.50), THRESHOLDS)
    assert len(failures) == 1 and "refusal gate 0.55" in failures[0]


def test_nothing_retrieved_counts_as_below_the_gate() -> None:
    results = [QuestionResult(QUESTION, None, None, ())] * 10
    assert len(check(results, THRESHOLDS)) == 3


def test_the_shipped_thresholds_load_and_match_the_configured_gate() -> None:
    from eka.config import Settings

    thresholds = load_thresholds(EVAL_DIR / "thresholds.json")
    assert thresholds.gate_cosine == Settings(_env_file=None, environment="test").refusal_min_cosine
    assert 0 < thresholds.min_mrr <= 1 and 0 < thresholds.min_hit_at_3 <= 1


def test_any_document_lets_the_text_alone_decide() -> None:
    other = hit("merged.txt", "Records are kept for 7 years.")
    assert not is_relevant(other, QUESTION)
    assert is_relevant(other, QUESTION, any_document=True)
    assert first_relevant_rank([other], QUESTION, any_document=True) == 1
    assert first_relevant_rank([other], QUESTION) is None


def test_the_question_set_is_at_least_doubled_and_the_new_rows_are_labelled_synthetic() -> None:
    import json

    rows = [
        json.loads(line)
        for line in (EVAL_DIR / "questions.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) >= 88
    assert sum(1 for r in rows if r.get("kind") == "hard") >= 20
    assert all(r.get("source") == "synthetic" for r in rows[44:])
    challenge = load_challenge(EVAL_DIR / "challenge.jsonl")
    assert len(challenge) >= 20
