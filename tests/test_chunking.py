# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""Chunker (TDD 4.4): the invariants are property-tested, the behaviour is shown by examples."""

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from eka.domain.models import Chunk, Segment
from eka.ingestion.chunking import (
    HARD_MAX_TOKENS,
    TokenCounter,
    chunk_config_label,
    chunk_document,
    chunk_segment,
)
from tests.fakes import FakeEmbedder

word_count = FakeEmbedder().count_tokens  # one token per word or punctuation mark


def char_count(text: str) -> int:
    """A counter where length matters, to exercise the oversized-word fallback."""
    return len(text) // 4 + (1 if text else 0)


PIECES = [
    "alpha",
    "beta",
    "gamma.",
    "delta,",
    "Epsilon!",
    "ünï",
    "x" * 25,
    "end.",
    "\n",
    "\n\n",
    "  ",
    "...",
    "(note)",
]

prose_text = st.lists(st.sampled_from(PIECES), min_size=1, max_size=150).map(" ".join)
HYPOTHESIS = settings(max_examples=120, deadline=None, suppress_health_check=[HealthCheck.too_slow])


def prose(text: str, page: int = 1) -> Segment:
    return Segment(text, {"type": "page", "page": page})


def non_space_positions(text: str) -> set[int]:
    return {i for i, c in enumerate(text) if not c.isspace()}


def check_invariants(
    segment: Segment, chunks: list[Chunk], count: TokenCounter, max_tokens: int, overlap: int
) -> None:
    keeps_indentation = segment.unit == "lines"  # code keeps its first line's indentation
    covered: set[int] = set()
    for chunk in chunks:
        assert chunk.text == segment.text[chunk.char_start : chunk.char_end]
        assert chunk.text == chunk.text.rstrip()
        assert keeps_indentation or chunk.text == chunk.text.lstrip()
        assert chunk.token_count == count(chunk.text)
        assert 0 < chunk.token_count <= max_tokens
        covered.update(range(chunk.char_start, chunk.char_end))
    assert non_space_positions(segment.text) <= covered, "some text is in no chunk"
    for previous, current in zip(chunks, chunks[1:], strict=False):
        assert current.char_start > previous.char_start  # always moves forward
        assert current.char_end > previous.char_end
        if current.char_start < previous.char_end:  # they overlap
            shared = segment.text[current.char_start : previous.char_end]
            assert count(shared) <= overlap


@HYPOTHESIS
@given(
    text=prose_text,
    max_tokens=st.integers(min_value=6, max_value=40),
    overlap_fraction=st.floats(min_value=0, max_value=0.9),
)
def test_prose_invariants_hold(text: str, max_tokens: int, overlap_fraction: float) -> None:
    overlap = min(max_tokens - 1, int(max_tokens * overlap_fraction))
    segment = prose(text)
    chunks = chunk_segment(segment, word_count, max_tokens=max_tokens, overlap_tokens=overlap)
    check_invariants(segment, chunks, word_count, max_tokens, overlap)


@HYPOTHESIS
@given(
    text=prose_text,
    max_tokens=st.integers(min_value=4, max_value=30),
    overlap_fraction=st.floats(min_value=0, max_value=0.9),
)
def test_oversized_words_are_cut_so_the_limit_still_holds(
    text: str, max_tokens: int, overlap_fraction: float
) -> None:
    glued = text + " " + "z" * 400  # one word far larger than the budget
    overlap = min(max_tokens - 1, int(max_tokens * overlap_fraction))
    segment = prose(glued)
    chunks = chunk_segment(segment, char_count, max_tokens=max_tokens, overlap_tokens=overlap)
    check_invariants(segment, chunks, char_count, max_tokens, overlap)


code_lines = st.lists(
    st.tuples(
        st.integers(min_value=0, max_value=3),  # indentation
        st.lists(st.sampled_from(["int", "x", "=", "1;", "return", "foo()", "{", "}"]), max_size=4),
    ),
    min_size=1,
    max_size=80,
)


@HYPOTHESIS
@given(lines=code_lines, max_tokens=st.integers(min_value=8, max_value=30))
def test_code_chunks_report_the_exact_lines_they_cover(
    lines: list[tuple[int, list[str]]], max_tokens: int
) -> None:
    rendered = ["    " * indent + " ".join(words) for indent, words in lines]
    if not any(line.strip() for line in rendered):
        return
    start_line = 17  # the segment starts somewhere inside a bigger file
    segment = Segment(
        "\n".join(rendered),
        {
            "type": "lines",
            "path": "A.java",
            "start": start_line,
            "end": start_line + len(rendered) - 1,
        },
        "lines",
    )
    chunks = chunk_segment(segment, word_count, max_tokens=max_tokens, overlap_tokens=2)
    check_invariants(segment, chunks, word_count, max_tokens, 2)
    for chunk in chunks:
        first, last = chunk.locator["start"], chunk.locator["end"]
        assert start_line <= first <= last <= start_line + len(rendered) - 1
        expected = "\n".join(rendered[first - start_line : last - start_line + 1]).rstrip()
        assert chunk.text == expected, "the line range must reproduce the chunk text"
        assert chunk.locator["path"] == "A.java"


# ----------------------------------------------------------------------------- examples


def test_a_short_segment_is_one_chunk() -> None:
    chunks = chunk_segment(prose("Just a short note."), word_count, max_tokens=50, overlap_tokens=5)
    assert len(chunks) == 1
    assert chunks[0].text == "Just a short note."
    assert chunks[0].locator == {"type": "page", "page": 1}


def test_paragraphs_are_kept_whole_when_they_fit() -> None:
    text = "First paragraph here.\n\nSecond paragraph here.\n\nThird paragraph here."
    chunks = chunk_segment(prose(text), word_count, max_tokens=10, overlap_tokens=0)
    assert [c.text for c in chunks] == [
        "First paragraph here.\n\nSecond paragraph here.",
        "Third paragraph here.",
    ]


def test_overlap_repeats_the_trailing_unit() -> None:
    text = "One two three.\n\nFour five six.\n\nSeven eight nine."
    chunks = chunk_segment(prose(text), word_count, max_tokens=9, overlap_tokens=4)
    assert chunks[0].text.endswith("Four five six.")
    assert chunks[1].text.startswith("Four five six.")


def test_a_long_paragraph_falls_back_to_sentences() -> None:
    sentences = [f"Sentence number {i} is here." for i in range(8)]
    chunks = chunk_segment(prose(" ".join(sentences)), word_count, max_tokens=14, overlap_tokens=0)
    assert len(chunks) > 1
    assert all(c.text.endswith(".") for c in chunks)  # never cut mid-sentence


def test_chunks_never_cross_a_segment_boundary_and_ordinals_run_on() -> None:
    first = prose("Page one has its own words.", page=1)
    second = prose("Page two has other words.", page=2)
    chunks = chunk_document([first, second], word_count, max_tokens=100, overlap_tokens=0)
    assert [c.ordinal for c in chunks] == [0, 1]
    assert [c.locator["page"] for c in chunks] == [1, 2]
    assert "two" not in chunks[0].text and "one" not in chunks[1].text


def test_code_keeps_a_method_whole_when_it_fits() -> None:
    method = "public int add(int a, int b) {\n    return a + b;\n}"
    other = "public int sub(int a, int b) {\n    return a - b;\n}"
    segment = Segment(
        f"{method}\n{other}", {"type": "lines", "path": "M.java", "start": 10, "end": 15}, "lines"
    )
    chunks = chunk_segment(segment, word_count, max_tokens=25, overlap_tokens=0)
    assert [c.text for c in chunks] == [method, other]
    assert [(c.locator["start"], c.locator["end"]) for c in chunks] == [(10, 12), (13, 15)]


def test_nothing_comes_out_of_a_blank_segment() -> None:
    assert chunk_segment(prose("   \n\n  "), word_count, max_tokens=10, overlap_tokens=0) == []


def test_the_real_limit_is_510_tokens() -> None:
    assert HARD_MAX_TOKENS == 510
    with pytest.raises(ValueError, match="max_tokens"):
        chunk_segment(prose("x"), word_count, max_tokens=511, overlap_tokens=0)
    with pytest.raises(ValueError, match="max_tokens"):
        chunk_segment(prose("x"), word_count, max_tokens=0, overlap_tokens=0)


def test_overlap_must_be_smaller_than_the_chunk() -> None:
    with pytest.raises(ValueError, match="overlap"):
        chunk_segment(prose("x"), word_count, max_tokens=10, overlap_tokens=10)
    with pytest.raises(ValueError, match="overlap"):
        chunk_segment(prose("x"), word_count, max_tokens=10, overlap_tokens=-1)


def test_the_config_label_records_the_settings() -> None:
    assert chunk_config_label(256, 32) == "tokens=256;overlap=32;v1"
