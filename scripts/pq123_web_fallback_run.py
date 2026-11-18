"""PQ1.2.3: web fallback hit-rate run against a live stack (real model). Paid: about 14 chat calls.

Env: EKA_RUN_KEY (a user API key, never printed). Usage:
  PYTHONPATH=src python scripts/pq123_web_fallback_run.py
      --out eval/reports/pq1-2-3-fallback-answers.jsonl
Groups: A corpus-answerable, B corpus-miss but answerable from the allowlisted pages,
C corpus-miss and not answerable anywhere.
"""

import argparse
import json
import os
import time
from pathlib import Path

import httpx

from eka.tools.answer_run import upload_corpus

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = [
    ("A1", "A", "How many days of paid annual leave does a full-time employee get?", "24 days"),
    ("A2", "A", "When do carried-over leave days expire?", "31 March"),
    ("A3", "A", "How far in advance must flights be booked?", "14 days"),
    ("A4", "A", "Within how many days must expense reports be submitted?", "30 days"),
    (
        "B1",
        "B",
        "Why can a default argument value that is a list cause surprising behaviour in Python?",
        "evaluated only once",
    ),
    ("B2", "B", "How can a Python list be used as a stack?", "append"),
    ("B3", "B", "Which Python standard library class should I use to implement a queue?", "deque"),
    ("B4", "B", "What does the pass statement do in Python?", "nothing"),
    ("B5", "B", "What is tuple packing in Python?", "packed together"),
    ("B6", "B", "What is a set in Python and what is it used for?", "no duplicate"),
    ("C1", "C", "Are pets allowed in the office?", None),
    ("C2", "C", "What is the company's stock ticker symbol?", None),
    ("C3", "C", "What is the policy on sabbatical leave?", None),
    ("C4", "C", "Which catering company runs the cafeteria?", None),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    key = os.environ["EKA_RUN_KEY"]
    with httpx.Client(base_url=args.base_url, headers={"X-API-Key": key}, timeout=180) as client:
        upload_corpus(client, ROOT / "eval" / "corpus", 300)
        rows = []
        for qid, group, question, key_phrase in QUESTIONS:
            started = time.monotonic()
            body = client.post(
                "/api/v1/chat", json={"question": question, "mode": "verified"}
            ).json()
            rows.append(
                {
                    "id": qid,
                    "group": group,
                    "question": question,
                    "key_phrase": key_phrase,
                    "answer": body["answer"],
                    "refused": body["refused"],
                    "refusal_reason": body["refusal_reason"],
                    "web_fallback": body["web_fallback"],
                    "verified": body["verified"],
                    "citations": [
                        {"kind": c["kind"], "file": c["filename"], "url": c.get("source_url")}
                        for c in body["citations"]
                    ],
                    "seconds": round(time.monotonic() - started, 2),
                }
            )
            last = rows[-1]
            print(
                qid,
                "fallback" if last["web_fallback"] else "-",
                "refused" if last["refused"] else "answered",
                last["seconds"],
                flush=True,
            )
    args.out.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
