"""Command line: ingest the evaluation corpus into a database, score retrieval, write a report.

Example (Git Bash, from the repository root, database already migrated):

    python -m eka.eval --database-url "$EKA_DATABASE_URL" --out eval/reports/baseline.md
"""

import argparse
import asyncio
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from eka.adapters.db.engine import Database
from eka.adapters.embedder_fastembed import FastEmbedEmbedder
from eka.adapters.reranker_fastembed import FastEmbedReranker
from eka.eval.dataset import load_challenge, load_questions
from eka.eval.gate import check, load_thresholds
from eka.eval.metrics import QuestionResult
from eka.eval.report import RunInfo, render_report
from eka.eval.runner import (
    EvalConfig,
    challenge_cosines,
    delete_corpus,
    ingest_corpus,
    run_questions,
)
from eka.services.retrieval import RetrievalSettings

ROOT = Path(__file__).resolve().parents[3]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m eka.eval", description=__doc__)
    parser.add_argument("--database-url", default=os.environ.get("EKA_DATABASE_URL"))
    parser.add_argument("--corpus", type=Path, default=ROOT / "eval" / "corpus")
    parser.add_argument("--questions", type=Path, default=ROOT / "eval" / "questions.jsonl")
    parser.add_argument("--challenge", type=Path, default=ROOT / "eval" / "challenge.jsonl")
    parser.add_argument("--model", default="BAAI/bge-small-en-v1.5")
    parser.add_argument("--model-cache", type=Path, default=ROOT / "data" / "models")
    parser.add_argument("--chunk-tokens", type=int, default=256)
    parser.add_argument("--overlap", type=int, default=32)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--out", type=Path, default=ROOT / "eval" / "reports" / "baseline.md")
    parser.add_argument("--thresholds", type=Path, default=ROOT / "eval" / "thresholds.json")
    parser.add_argument(
        "--mode",
        choices=("hybrid", "dense", "sparse"),
        default="hybrid",
        help="which retrieval paths to use (experiment E2)",
    )
    parser.add_argument(
        "--check", action="store_true", help="exit with status 1 if the run misses a threshold"
    )
    parser.add_argument(
        "--rerank",
        nargs="?",
        const="Xenova/ms-marco-MiniLM-L-6-v2",
        default=None,
        metavar="MODEL",
        help="re-order the top fused candidates with a cross-encoder (experiment E3)",
    )
    parser.add_argument(
        "--any-document",
        action="store_true",
        help="count a passage as relevant by its text alone (for a corpus merged into one file)",
    )
    return parser


async def _run(args: argparse.Namespace) -> tuple[str, list[QuestionResult]]:
    embedder = FastEmbedEmbedder(args.model, args.model_cache, 384)
    config = EvalConfig(
        chunk_tokens=args.chunk_tokens,
        chunk_overlap_tokens=args.overlap,
        top_k=args.top_k,
        retrieval=RetrievalSettings(mode=args.mode),
        any_document=args.any_document,
        reranker=FastEmbedReranker(args.rerank, args.model_cache) if args.rerank else None,
    )
    questions = load_questions(args.questions)
    challenge = load_challenge(args.challenge)
    owner = f"eval-{uuid.uuid4().hex[:8]}"
    database = Database(args.database_url)
    try:
        try:
            summary = await ingest_corpus(database, owner, args.corpus, embedder, config)
            results = await run_questions(database, owner, embedder, config, questions)
            cosines = await challenge_cosines(database, owner, embedder, config, challenge)
        finally:
            await delete_corpus(database, owner)
    finally:
        await database.dispose()
    info = RunInfo(
        model=args.model,
        chunk_tokens=args.chunk_tokens,
        chunk_overlap_tokens=args.overlap,
        top_k=args.top_k,
        documents=summary.documents,
        chunks=summary.chunks,
        date=datetime.now(UTC).date().isoformat(),
    )
    return render_report(info, results, cosines), results


def main() -> int:
    args = _parser().parse_args()
    if not args.database_url:
        print("Set --database-url or EKA_DATABASE_URL.", file=sys.stderr)
        return 2
    # psycopg's async mode cannot use Windows' default ProactorEventLoop.
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        report, results = runner.run(_run(args))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report, encoding="utf-8")
    print(report)
    print(f"Written to {args.out}")
    if args.check:
        failures = check(results, load_thresholds(args.thresholds))
        for failure in failures:
            print(f"REGRESSION: {failure}", file=sys.stderr)
        if failures:
            return 1
        print("Regression gate: passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
