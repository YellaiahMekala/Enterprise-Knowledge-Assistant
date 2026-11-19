# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""Evaluation question sets, read from JSON Lines files."""

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Question:
    """An answerable question. A retrieved passage is relevant when it comes from ``doc`` and its
    text contains ``gold`` (case-insensitive). ``kind`` is lexical, paraphrase or exact."""

    id: str
    question: str
    doc: str
    gold: str
    kind: str


@dataclass(frozen=True, slots=True)
class ChallengeQuestion:
    """A question the corpus cannot answer. Used to calibrate the refusal threshold."""

    id: str
    question: str


def _rows(path: Path) -> list[dict[str, str]]:
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as error:
            raise ValueError(f"{path.name}:{number}: not valid JSON") from error
    return rows


def load_questions(path: Path) -> list[Question]:
    questions = [
        Question(
            id=row["id"],
            question=row["question"],
            doc=row["doc"],
            gold=row["gold"],
            kind=row.get("kind", "lexical"),
        )
        for row in _rows(path)
    ]
    ids = [q.id for q in questions]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path.name}: duplicate question ids")
    return questions


def load_challenge(path: Path) -> list[ChallengeQuestion]:
    return [ChallengeQuestion(id=row["id"], question=row["question"]) for row in _rows(path)]
