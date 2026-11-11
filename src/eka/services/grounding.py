"""Citation grounding: does a cited passage support the sentence that cites it?

The answer check in ``answering.verify`` already rejects a citation number that was not sent. This
module catches the other mistake seen in the live run (q29): a correct sentence that cites the
wrong passage. The check is word overlap, not meaning, so it only flags clear cases: a citation is
misattributed when the cited passages cover less than half of the sentence's content words and
another sent passage covers at least half and twice as many. A paraphrase that matches no passage
well is left alone; it is not the job of this check.
"""

import re
from collections.abc import Sequence

_CITATION_RUN = re.compile(r"(?:\s*\[\d{1,3}\])+")
_NUMBER = re.compile(r"\[(\d{1,3})\]")
_WORD = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "are",
        "was",
        "were",
        "with",
        "that",
        "this",
        "from",
        "have",
        "has",
        "not",
        "but",
        "you",
        "your",
        "can",
        "may",
        "must",
        "will",
        "its",
        "into",
        "than",
        "then",
        "they",
        "them",
        "their",
        "there",
        "what",
        "when",
        "which",
        "who",
        "how",
        "why",
        "all",
        "any",
        "each",
        "per",
        "use",
        "used",
        "also",
        "only",
        "should",
        "would",
        "could",
        "been",
        "being",
        "does",
        "did",
        "our",
        "out",
        "off",
    }
)
SUPPORTED = 0.5
BETTER_BY = 2.0


def content_terms(text: str) -> set[str]:
    """Lower-case words of 3+ characters that are not stopwords, plus every number."""
    return {
        word
        for word in _WORD.findall(text.lower())
        if word.isdigit() or (len(word) >= 3 and word not in _STOPWORDS)
    }


def cited_claims(text: str) -> list[tuple[str, tuple[int, ...]]]:
    """Split an answer into (claim text, cited numbers). A claim is the text since the previous
    run of citations, so both "fact [1]." and "fact. [1]" work."""
    claims: list[tuple[str, tuple[int, ...]]] = []
    start = 0
    for run in _CITATION_RUN.finditer(text):
        numbers = tuple(int(n) for n in _NUMBER.findall(run.group()))
        claim = text[start : run.start()].strip(" .,;:\n")
        if claim:
            claims.append((claim, numbers))
        start = run.end()
    return claims


def _coverage(terms: set[str], passage_terms: set[str]) -> float:
    return len(terms & passage_terms) / len(terms)


def misattributed(text: str, passages: Sequence[str]) -> tuple[int, ...]:
    """Numbers of the citations whose claim another passage clearly supports better.

    Citation numbers outside ``1..len(passages)`` are ignored here (``verify`` rejects them)."""
    passage_terms = [content_terms(p) for p in passages]
    wrong: list[int] = []
    for claim, numbers in cited_claims(text):
        terms = content_terms(claim)
        valid = [n for n in numbers if 1 <= n <= len(passages)]
        if len(terms) < 2 or not valid:
            continue
        cited = _coverage(terms, set().union(*(passage_terms[n - 1] for n in valid)))
        if cited >= SUPPORTED:
            continue
        others = [
            _coverage(terms, passage_terms[i]) for i in range(len(passages)) if i + 1 not in valid
        ]
        best_other = max(others, default=0.0)
        if best_other >= SUPPORTED and best_other >= BETTER_BY * cited:
            wrong.extend(n for n in valid if n not in wrong)
    return tuple(wrong)
