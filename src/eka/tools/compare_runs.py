# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""Compare answer runs of the same questions from different chat providers, as a Markdown table.

    python -m eka.tools.compare_runs --run openai=eval/reports/run_openai.jsonl \
        --run bedrock=eval/reports/run_bedrock.jsonl --out eval/reports/providers.md

Each run is the JSON lines file written by ``eka.tools.answer_run``; the label is yours, so name
the provider and model that really answered (the core does not report it per answer). The same
mechanical scores as answer_run are used: "fact found" is a string match of the gold text, so a
correct paraphrase counts as a miss and the differences listed at the end need reading by a person.
"""

import argparse
import json
from pathlib import Path

from eka.tools.answer_run import Answer, summarise


def load(path: Path) -> list[Answer]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [Answer(**json.loads(line)) for line in lines if line]


def _outcome(answer: Answer) -> str:
    if answer.refused:
        return "refused"
    if not answer.gold:
        return "answered"
    if answer.fact_found and answer.doc_cited:
        return "fact + doc"
    if answer.fact_found:
        return "fact, wrong doc"
    return "doc only" if answer.doc_cited else "miss"


def report(runs: dict[str, list[Answer]]) -> str:
    ids = [{a.id for a in answers} for answers in runs.values()]
    if any(i != ids[0] for i in ids):
        raise ValueError("the runs did not ask the same questions")
    labels = list(runs)
    summaries = {label: summarise(answers) for label, answers in runs.items()}
    first = summaries[labels[0]]

    def row(name: str, values: list[str]) -> str:
        return f"| {name} | " + " | ".join(values) + " |"

    lines = [
        row("Measure", labels),
        "|---|" + "---|" * len(labels),
        row(
            f"Fact found (of {first['answerable']} answerable)",
            [str(summaries[x]["fact_found"]) for x in labels],
        ),
        row("Expected document cited", [str(summaries[x]["expected_doc_cited"]) for x in labels]),
        row("Wrong refusals", [str(len(summaries[x]["wrong_refusals"])) for x in labels]),
        row(
            f"Unanswerable refused (of {first['challenge']})",
            [str(summaries[x]["challenge_refused"]) for x in labels],
        ),
        row(
            "Verified answers",
            [str(sum(a.verified for a in runs[x] if not a.refused)) for x in labels],
        ),
        row("Median seconds (answerable)", [str(summaries[x]["median_seconds"]) for x in labels]),
    ]
    by_id = {label: {a.id: a for a in answers} for label, answers in runs.items()}
    differ = [
        qid for qid in sorted(ids[0]) if len({_outcome(by_id[label][qid]) for label in labels}) > 1
    ]
    lines += ["", f"Questions with different outcomes: {len(differ)}", ""]
    if differ:
        lines += [row("Question", labels), "|---|" + "---|" * len(labels)]
        lines += [row(qid, [_outcome(by_id[x][qid]) for x in labels]) for qid in differ]
    return "\n".join(lines) + "\n"


def _run(value: str) -> tuple[str, Path]:
    label, sep, path = value.partition("=")
    if not sep or not label or not path:
        raise argparse.ArgumentTypeError("use label=path")
    return label, Path(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eka.tools.compare_runs", description=__doc__)
    parser.add_argument("--run", type=_run, action="append", required=True, help="label=path")
    parser.add_argument("--out", type=Path, help="also write the table to this file")
    args = parser.parse_args(argv)
    if len(args.run) < 2:
        parser.error("give at least two --run")
    text = report({label: load(path) for label, path in args.run})
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
