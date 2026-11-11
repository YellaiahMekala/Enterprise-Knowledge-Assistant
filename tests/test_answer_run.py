"""Scoring of the answer-run tool (no network)."""

from eka.tools.answer_run import Answer, summarise


def _answer(id: str, gold: str | None, text: str, docs: list[str], refused: bool) -> Answer:
    return Answer(
        id,
        "lexical",
        "q?",
        "a.md" if gold else None,
        gold,
        text,
        docs,
        refused,
        "weak_evidence" if refused else None,
        True,
        1.0,
    )


def test_summary_counts_facts_citations_and_refusals() -> None:
    summary = summarise(
        [
            _answer("q1", "5 minutes", "Within 5 Minutes [1].", ["a.md"], False),
            _answer("q2", "14", "Fourteen [1].", ["b.md"], False),
            _answer("q3", "x", "I could not find this.", [], True),
            _answer("c1", None, "I could not find this.", [], True),
            _answer("c2", None, "Made up [1].", ["b.md"], False),
        ]
    )
    assert summary["fact_found"] == 1 and summary["expected_doc_cited"] == 1
    assert summary["wrong_refusals"] == ["q3"]
    assert summary["answered_but_doc_not_cited"] == ["q2"]
    assert summary["challenge_refused"] == 1 and summary["challenge_answered"] == ["c2"]
