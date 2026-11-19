# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""Citation grounding (live-run defect q29): another passage must not clearly beat the cited one."""

import pytest

from eka.services.grounding import cited_claims, content_terms, misattributed

INCIDENT = (
    "For a SEV1 the on-call engineer must acknowledge the page within 5 minutes and an incident "
    "commander is named within 15 minutes."
)
RETRY = "public final class RetryPolicy { public static final int MAX_ATTEMPTS = 5; }"
LEAVE = "Employees get 25 days of paid annual leave per calendar year."


def test_content_terms_keep_numbers_and_drop_stopwords() -> None:
    assert content_terms("The page within 5 minutes, and an SEV1!") == {
        "page",
        "within",
        "5",
        "minutes",
        "sev1",
    }


@pytest.mark.parametrize(
    ("text", "claims"),
    [
        ("A fact [1].", [("A fact", (1,))]),
        ("A fact. [1] Another [2][3].", [("A fact", (1,)), ("Another", (2, 3))]),
        ("No citation.", []),
    ],
)
def test_cited_claims(text: str, claims: list[tuple[str, tuple[int, ...]]]) -> None:
    assert cited_claims(text) == claims


def test_q29_wrong_citation_is_flagged() -> None:
    answer = "The on-call engineer must acknowledge a SEV1 page within 5 minutes [2]."
    assert misattributed(answer, [INCIDENT, RETRY]) == (2,)


def test_the_right_citation_passes() -> None:
    answer = "The on-call engineer must acknowledge a SEV1 page within 5 minutes [1]."
    assert misattributed(answer, [INCIDENT, RETRY]) == ()


def test_citing_both_passes_when_together_they_support_the_claim() -> None:
    answer = "The on-call engineer must acknowledge a SEV1 page within 5 minutes [1][2]."
    assert misattributed(answer, [INCIDENT, RETRY]) == ()


def test_a_paraphrase_no_passage_matches_well_is_not_flagged() -> None:
    # Low overlap everywhere: not this check's business (the model may paraphrase).
    answer = "You are entitled to twenty-five holidays a year [1]."
    assert misattributed(answer, [LEAVE, RETRY]) == ()


def test_short_claims_and_unknown_numbers_are_ignored() -> None:
    assert misattributed("Five [2].", [INCIDENT, RETRY]) == ()
    assert misattributed("Acknowledge within 5 minutes [9].", [INCIDENT, RETRY]) == ()


def test_only_the_wrong_sentence_is_reported() -> None:
    answer = (
        "Employees get 25 days of paid annual leave [1]. "
        "The engineer must acknowledge a SEV1 page within 5 minutes [1]."
    )
    assert misattributed(answer, [LEAVE, INCIDENT]) == (1,)
