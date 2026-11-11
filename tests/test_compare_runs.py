"""Provider comparison table built from answer-run files (no network)."""

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from eka.tools.answer_run import Answer
from eka.tools.compare_runs import load, main, report


def _answer(id: str, gold: str | None, text: str, docs: list[str], refused: bool) -> Answer:
    return Answer(
        id, "lexical", "q?", "a.md" if gold else None, gold, text, docs, refused,
        "weak_evidence" if refused else None, not refused, 2.0,
    )  # fmt: skip


RUN_A = [
    _answer("q1", "5 minutes", "Within 5 minutes [1].", ["a.md"], False),
    _answer("q2", "14", "14 days [1].", ["a.md"], False),
    _answer("c1", None, "I could not find this.", [], True),
]
RUN_B = [
    _answer("q1", "5 minutes", "Within 5 minutes [1].", ["a.md"], False),
    _answer("q2", "14", "I could not find this.", [], True),
    _answer("c1", None, "Made up [1].", ["b.md"], False),
]


def test_table_has_one_column_per_run_and_lists_only_differences() -> None:
    text = report({"fake": RUN_A, "bedrock-stub": RUN_B})

    assert "| Measure | fake | bedrock-stub |" in text
    assert "| Fact found (of 2 answerable) | 2 | 1 |" in text
    assert "| Wrong refusals | 0 | 1 |" in text
    assert "| Unanswerable refused (of 1) | 1 | 0 |" in text
    assert "Questions with different outcomes: 2" in text
    assert "| q2 | fact + doc | refused |" in text
    assert "| c1 | refused | answered |" in text
    assert "| q1 |" not in text


def test_runs_over_different_questions_are_rejected() -> None:
    with pytest.raises(ValueError, match="same questions"):
        report({"a": RUN_A, "b": RUN_B[:2]})


def test_cli_reads_answer_run_files_and_writes_the_table(tmp_path: Path) -> None:
    for name, run in (("a.jsonl", RUN_A), ("b.jsonl", RUN_B)):
        (tmp_path / name).write_text(
            "".join(json.dumps(asdict(a)) + "\n" for a in run), encoding="utf-8"
        )
    out = tmp_path / "table.md"

    code = main(["--run", f"x={tmp_path / 'a.jsonl'}", "--run", f"y={tmp_path / 'b.jsonl'}",
                 "--out", str(out)])  # fmt: skip

    assert code == 0
    assert "| Measure | x | y |" in out.read_text(encoding="utf-8")
    assert load(tmp_path / "a.jsonl") == RUN_A
