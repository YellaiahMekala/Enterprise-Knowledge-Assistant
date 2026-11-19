# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""The evaluation harness against a real database with the fake embedder. This proves the harness
works end to end (upload, queue, chunk, store, search, score). It says nothing about retrieval
quality: the fake embedder is not a language model."""

from pathlib import Path

from eka.adapters.db.engine import Database
from eka.eval.dataset import load_challenge, load_questions
from eka.eval.metrics import QuestionResult, hit_rate
from eka.eval.runner import (
    EvalConfig,
    challenge_cosines,
    delete_corpus,
    ingest_corpus,
    run_questions,
)
from tests.fakes import FakeEmbedder
from tests.integration.helpers import admin_engine, count, run_async, unique_owner

EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"


def test_the_harness_ingests_scores_and_cleans_up(isolated_url: str) -> None:
    owner = unique_owner("eval")
    embedder = FakeEmbedder()
    config = EvalConfig()
    questions = load_questions(EVAL_DIR / "questions.jsonl")
    challenge = load_challenge(EVAL_DIR / "challenge.jsonl")

    async def scenario() -> tuple[int, int, list[float], list[QuestionResult]]:
        database = Database(isolated_url)
        try:
            summary = await ingest_corpus(database, owner, EVAL_DIR / "corpus", embedder, config)
            results = await run_questions(database, owner, embedder, config, questions)
            cosines = await challenge_cosines(database, owner, embedder, config, challenge)
            await delete_corpus(database, owner)
            return summary.documents, summary.chunks, cosines, results
        finally:
            await database.dispose()

    documents, chunks, cosines, results = run_async(scenario)
    corpus_files = [p for p in (EVAL_DIR / "corpus").iterdir() if p.is_file()]
    assert documents == len(corpus_files)
    assert chunks >= documents
    assert len(results) == len(questions)
    assert len(cosines) == len(challenge)
    assert hit_rate(results, config.top_k) > 0.5
    engine = admin_engine(isolated_url)
    assert count(engine, "documents", "owner_id = :o", o=owner) == 0
    assert count(engine, "chunks", "owner_id = :o", o=owner) == 0
