"""Ask the evaluation questions through the running API and score the answers.

    python -m eka.tools.answer_run --base-url http://127.0.0.1:8000 --out eval/reports/run.jsonl

The API key is read from the EKA_RUN_API_KEY environment variable, never from the command line.
The corpus is uploaded first (an already-uploaded file is reused) and the tool waits until every
document is ready, so a worker must be running. Each answer is one JSON line; the summary is
printed. Which model answers is whatever the API is configured with: this tool never calls a
model itself.

With EKA_RUN_ADMIN_KEY also set (an admin key), the tool then prints the run's tokens, cost and
time-to-first-token percentiles from the admin usage report (ADR-037).

Scores are mechanical: "fact found" is a case-insensitive string match of the gold text, so a
correct paraphrase counts as a miss and has to be read by a person.
"""

import argparse
import json
import os
import sys
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True, slots=True)
class Answer:
    id: str
    kind: str
    question: str
    expected_doc: str | None
    gold: str | None
    answer: str
    cited_docs: list[str]
    refused: bool
    refusal_reason: str | None
    verified: bool
    seconds: float

    @property
    def fact_found(self) -> bool:
        return self.gold is not None and self.gold.lower() in self.answer.lower()

    @property
    def doc_cited(self) -> bool:
        return self.expected_doc in self.cited_docs


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def upload_corpus(client: httpx.Client, corpus: Path, timeout: float) -> None:
    for path in sorted(p for p in corpus.iterdir() if p.is_file()):
        response = client.post("/api/v1/documents", files={"file": (path.name, path.read_bytes())})
        response.raise_for_status()
    deadline = time.monotonic() + timeout
    while True:
        items = client.get("/api/v1/documents", params={"limit": 100}).json()["items"]
        pending = [d["filename"] for d in items if d["status"] not in ("ready", "failed")]
        failed = [d["filename"] for d in items if d["status"] == "failed"]
        if failed:
            raise RuntimeError(f"documents failed ingestion: {failed}")
        if not pending:
            return
        if time.monotonic() > deadline:
            raise RuntimeError(f"documents not ready in time: {pending}")
        time.sleep(1)


def ask(client: httpx.Client, item: dict[str, Any], mode: str) -> Answer:
    started = time.monotonic()
    response = client.post("/api/v1/chat", json={"question": item["question"], "mode": mode})
    response.raise_for_status()
    body = response.json()
    return Answer(
        id=item["id"],
        kind=item.get("kind", "challenge"),
        question=item["question"],
        expected_doc=item.get("doc"),
        gold=item.get("gold"),
        answer=body["answer"],
        cited_docs=sorted({c["filename"] for c in body["citations"]}),
        refused=body["refused"],
        refusal_reason=body["refusal_reason"],
        verified=body["verified"],
        seconds=round(time.monotonic() - started, 2),
    )


def summarise(answers: Iterable[Answer]) -> dict[str, Any]:
    answers = list(answers)
    answerable = [a for a in answers if a.gold]
    challenge = [a for a in answers if not a.gold]
    seconds = sorted(a.seconds for a in answerable)
    return {
        "answerable": len(answerable),
        "fact_found": sum(a.fact_found for a in answerable),
        "expected_doc_cited": sum(a.doc_cited for a in answerable),
        "wrong_refusals": [a.id for a in answerable if a.refused],
        "answered_but_doc_not_cited": [
            a.id for a in answerable if not a.refused and not a.doc_cited
        ],
        "challenge": len(challenge),
        "challenge_refused": sum(a.refused for a in challenge),
        "challenge_answered": [a.id for a in challenge if not a.refused],
        "refusal_reasons": sorted({a.refusal_reason or "" for a in answers if a.refused}),
        "median_seconds": seconds[len(seconds) // 2] if seconds else None,
    }


def usage_summary(client: httpx.Client, start: datetime, end: datetime) -> dict[str, Any]:
    """Tokens, cost and first-token times for the run window, per user, from the usage report."""
    response = client.get(
        "/api/v1/admin/usage",
        params={"group_by": "user", "from": start.isoformat(), "to": end.isoformat()},
    )
    response.raise_for_status()
    rows = response.json()["rows"]
    requests = sum(r["requests"] for r in rows)
    costs = [r["cost_usd"] for r in rows if r["cost_usd"] is not None]
    cost = sum(costs) if costs else None
    return {
        "requests": requests,
        "prompt_tokens": sum(r["prompt_tokens"] or 0 for r in rows),
        "completion_tokens": sum(r["completion_tokens"] or 0 for r in rows),
        "cost_usd": round(cost, 6) if cost is not None else None,
        "cost_per_100_questions_usd": (
            round(cost * 100 / requests, 4) if cost is not None and requests else None
        ),
        "per_user": rows,  # p50 and p95 latency and time to first token per user
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m eka.tools.answer_run", description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--corpus", type=Path, default=ROOT / "eval" / "corpus")
    parser.add_argument("--questions", type=Path, default=ROOT / "eval" / "questions.jsonl")
    parser.add_argument("--challenge", type=Path, default=ROOT / "eval" / "challenge.jsonl")
    parser.add_argument("--mode", choices=("verified", "fast"), default="verified")
    parser.add_argument("--only", nargs="*", help="question ids to ask (default: all)")
    parser.add_argument("--out", type=Path, required=True, help="JSON lines, one per answer")
    parser.add_argument("--ingest-timeout", type=float, default=300.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    key = os.environ.get("EKA_RUN_API_KEY")
    if not key:
        print("Set EKA_RUN_API_KEY to an API key of the user to run as.", file=sys.stderr)
        return 2
    items = _jsonl(args.questions) + _jsonl(args.challenge)
    if args.only:
        items = [i for i in items if i["id"] in set(args.only)]
    with httpx.Client(base_url=args.base_url, headers={"X-API-Key": key}, timeout=120) as client:
        upload_corpus(client, args.corpus, args.ingest_timeout)
        started = datetime.now(UTC)
        answers = [ask(client, item, args.mode) for item in items]
        ended = datetime.now(UTC) + timedelta(seconds=1)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as out:
        for answer in answers:
            out.write(json.dumps(asdict(answer)) + "\n")
    print(json.dumps(summarise(answers), indent=2))
    admin_key = os.environ.get("EKA_RUN_ADMIN_KEY")
    if admin_key:
        headers = {"X-API-Key": admin_key}
        with httpx.Client(base_url=args.base_url, headers=headers, timeout=60) as admin:
            print(json.dumps({"usage": usage_summary(admin, started, ended)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
