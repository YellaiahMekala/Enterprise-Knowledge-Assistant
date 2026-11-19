# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
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


def test_usage_summary_sums_the_report_and_prices_100_questions() -> None:
    from datetime import UTC, datetime

    import httpx

    from eka.tools.answer_run import usage_summary

    rows = [
        {"key": "u1", "requests": 3, "prompt_tokens": 3000, "completion_tokens": 90,
         "cost_usd": 0.0006, "refused": 0},
        {"key": "u2", "requests": 1, "prompt_tokens": 900, "completion_tokens": 30,
         "cost_usd": None, "refused": 1},
    ]  # fmt: skip
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"rows": rows})

    client = httpx.Client(base_url="http://api", transport=httpx.MockTransport(handler))
    start, end = datetime(2026, 11, 12, tzinfo=UTC), datetime(2026, 11, 13, tzinfo=UTC)
    summary = usage_summary(client, start, end)
    assert seen[0].url.params["group_by"] == "user"
    assert summary["requests"] == 4 and summary["prompt_tokens"] == 3900
    assert summary["cost_usd"] == 0.0006 and summary["cost_per_100_questions_usd"] == 0.015
