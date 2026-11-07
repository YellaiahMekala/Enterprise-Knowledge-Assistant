"""Merge the policy documents of ``eval/corpus`` into one plain-text handbook for the chunk-size
experiment, and write the matching question subset.

One long text makes chunk size matter: with separate short files every file is one chunk at any
size. CSV and Java files are left out (they do not read as handbook prose), and so are their
questions. Run: python eval/build_handbook.py
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCES = sorted(p for p in (ROOT / "corpus").iterdir() if p.suffix in {".md", ".txt"})


def paragraphs(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    lines = [re.sub(r"^#+\s*", "", line).strip() for line in text.splitlines()]
    return [line for line in lines if line]


def main() -> None:
    out = ROOT / "corpus_handbook"
    out.mkdir(exist_ok=True)
    blocks = ["\n".join(paragraphs(p)) for p in SOURCES]
    (out / "handbook.txt").write_text("\n\n".join(blocks) + "\n", encoding="utf-8")

    kept = {p.name for p in SOURCES}
    rows = [
        json.loads(line)
        for line in (ROOT / "questions.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    subset = [row for row in rows if row["doc"] in kept]
    (ROOT / "questions_handbook.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in subset), encoding="utf-8"
    )
    print(f"handbook.txt: {len(SOURCES)} files merged; {len(subset)} of {len(rows)} questions kept")


if __name__ == "__main__":
    main()
