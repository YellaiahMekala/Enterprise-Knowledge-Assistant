# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""Chunker (TDD 4.4, ADR-007, ADR-029).

Input: segments. Output: chunks that are exact slices of their segment's cleaned text.

1. Split a segment into *units*: paragraphs, then sentences for paragraphs over the budget, then
   words for sentences over the budget, then characters for a single oversized word. Code
   segments use lines first.
2. Count tokens with the embedding model's own tokenizer (passed in as ``count_tokens``), so the
   limit is exact rather than estimated.
3. Pack whole units greedily while the *slice's* token count stays within the budget.
4. Start the next chunk with trailing units of the previous one, at most ``overlap_tokens``.
5. A chunk never crosses a segment boundary, so a page, section, row-group or line-range
   citation is always exact. Overlap applies only inside a segment.

Invariants (property-tested): ``token_count <= max_tokens``; every non-whitespace character of
the segment is in at least one chunk; consecutive chunks overlap by at most ``overlap_tokens``;
``ordinal`` is dense; ``text == segment.text[char_start:char_end]``.
"""

import re
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from eka.domain.models import Chunk, Segment

TokenCounter = Callable[[str], int]
Span = tuple[int, int]

# 512 (model input) minus the two special tokens added when embedding.
HARD_MAX_TOKENS = 510

_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n")
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"\S+")


def _trim(text: str, start: int, end: int) -> Span | None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return (start, end) if start < end else None


def _split_on(pattern: re.Pattern[str], text: str, start: int, end: int) -> list[Span]:
    spans: list[Span] = []
    position = start
    for match in pattern.finditer(text, start, end):
        trimmed = _trim(text, position, match.start())
        if trimmed:
            spans.append(trimmed)
        position = match.end()
    trimmed = _trim(text, position, end)
    if trimmed:
        spans.append(trimmed)
    return spans


def _words(text: str, start: int, end: int) -> list[Span]:
    return [(m.start(), m.end()) for m in _WORD.finditer(text, start, end)]


def _split_characters(text: str, span: Span, budget: int, count: TokenCounter) -> list[Span]:
    """A single token-heavy word (a hash, base64): cut it at the longest prefix that fits."""
    start, end = span
    pieces: list[Span] = []
    while start < end:
        low, high = start + 1, end
        while low < high:  # longest prefix with count <= budget
            middle = (low + high + 1) // 2
            if count(text[start:middle]) <= budget:
                low = middle
            else:
                high = middle - 1
        pieces.append((start, low))
        start = low
    return pieces


def _fit(text: str, span: Span, budget: int, count: TokenCounter, level: int) -> list[Span]:
    """Split ``span`` until every piece fits the budget. ``level`` picks the next splitter."""
    if count(text[span[0] : span[1]]) <= budget:
        return [span]
    splitters: list[Callable[[], list[Span]]] = [
        lambda: _split_on(_PARAGRAPH_BREAK, text, *span),
        lambda: _split_on(_SENTENCE_BREAK, text, *span),
        lambda: _words(text, *span),
    ]
    while level < len(splitters):
        pieces = splitters[level]()
        level += 1
        if len(pieces) > 1:
            result: list[Span] = []
            for piece in pieces:
                result.extend(_fit(text, piece, budget, count, level))
            return result
    return _split_characters(text, span, budget, count)


def _line_spans(text: str) -> list[Span]:
    spans: list[Span] = []
    position = 0
    for line in text.split("\n"):
        end = position + len(line)
        trimmed_end = end
        while trimmed_end > position and text[trimmed_end - 1].isspace():
            trimmed_end -= 1
        if trimmed_end > position and text[position:trimmed_end].strip():
            spans.append((position, trimmed_end))  # keep indentation
        position = end + 1
    return spans


def _units(segment: Segment, budget: int, count: TokenCounter) -> list[Span]:
    text = segment.text
    if segment.unit == "lines":
        raw = _line_spans(text)
        level = 2  # a line over the budget goes straight to words
    else:
        raw = _split_on(_PARAGRAPH_BREAK, text, 0, len(text))
        level = 1
    units: list[Span] = []
    for span in raw:
        units.extend(_fit(text, span, budget, count, level))
    return units


def _refine_locator(segment: Segment, start: int, end: int) -> Mapping[str, Any]:
    """Pages, sections and row groups keep the segment's locator. A line range is narrowed to
    the lines the chunk actually covers, so a code citation points at the right lines."""
    locator = segment.locator
    if locator.get("type") != "lines":
        return locator
    first = int(locator["start"]) + segment.text.count("\n", 0, start)
    last = int(locator["start"]) + segment.text.count("\n", 0, end)
    return {**locator, "start": first, "end": last}


def chunk_segment(
    segment: Segment,
    count_tokens: TokenCounter,
    *,
    max_tokens: int,
    overlap_tokens: int,
    first_ordinal: int = 0,
) -> list[Chunk]:
    if not 0 < max_tokens <= HARD_MAX_TOKENS:
        raise ValueError(f"max_tokens must be in 1..{HARD_MAX_TOKENS}")
    if not 0 <= overlap_tokens < max_tokens:
        raise ValueError("overlap_tokens must be in 0..max_tokens-1")

    text = segment.text
    units = _units(segment, max_tokens, count_tokens)
    chunks: list[Chunk] = []
    first = 0
    while first < len(units):
        last = first
        while (
            last + 1 < len(units)
            and count_tokens(text[units[first][0] : units[last + 1][1]]) <= max_tokens
        ):
            last += 1
        start, end = units[first][0], units[last][1]
        chunks.append(
            Chunk(
                ordinal=first_ordinal + len(chunks),
                text=text[start:end],
                locator=_refine_locator(segment, start, end),
                char_start=start,
                char_end=end,
                token_count=count_tokens(text[start:end]),
            )
        )
        if last + 1 >= len(units):
            break
        # Overlap: step back over whole units while the shared slice stays within the limit,
        # but always move forward by at least one unit.
        next_first = last + 1
        while (
            next_first - 1 > first
            and count_tokens(text[units[next_first - 1][0] : units[last][1]]) <= overlap_tokens
        ):
            next_first -= 1
        # The next chunk must also hold at least one new unit. If the overlap leaves no room for
        # it, give some of the overlap back (it can shrink to nothing: a lone unit always fits).
        while (
            next_first <= last
            and count_tokens(text[units[next_first][0] : units[last + 1][1]]) > max_tokens
        ):
            next_first += 1
        first = next_first
    return chunks


def chunk_document(
    segments: Iterable[Segment],
    count_tokens: TokenCounter,
    *,
    max_tokens: int,
    overlap_tokens: int,
) -> list[Chunk]:
    """Chunk every segment in order; ordinals run densely across the whole document."""
    chunks: list[Chunk] = []
    for segment in segments:
        chunks.extend(
            chunk_segment(
                segment,
                count_tokens,
                max_tokens=max_tokens,
                overlap_tokens=overlap_tokens,
                first_ordinal=len(chunks),
            )
        )
    return chunks


def chunk_config_label(max_tokens: int, overlap_tokens: int) -> str:
    """Stored with every chunk so a change of settings is visible in the data (FR-15)."""
    return f"tokens={max_tokens};overlap={overlap_tokens};v1"
