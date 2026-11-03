"""Text cleaning (TDD 4.3): table-driven cases."""

import pytest

from eka.ingestion.cleaning import clean_lines, clean_prose


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("plain text", "plain text"),
        ("  padded  ", "padded"),
        ("two   spaces\tand\ttabs", "two spaces and tabs"),
        ("non breaking", "non breaking"),
        ("ﬁne ligature", "fine ligature"),  # NFKC
        ("ctrl\x00\x07chars", "ctrlchars"),
        ("line one\r\nline two\rline three", "line one\nline two\nline three"),
        ("inter-\nnational", "international"),  # hyphenation across a line break
        ("well-known\nword", "well-known\nword"),  # a real hyphen followed by a break is kept
        ("a\n\n\n\n\nb", "a\n\nb"),
        ("trailing \n next", "trailing\nnext"),
        ("", ""),
    ],
)
def test_clean_prose(raw: str, expected: str) -> None:
    assert clean_prose(raw) == expected


def test_clean_lines_keeps_every_line_and_the_indentation() -> None:
    raw = "def f():\r\n    return 1   \r\n\r\n\r\n\r\nx = 2\x00"
    cleaned = clean_lines(raw)
    assert cleaned == "def f():\n    return 1\n\n\n\nx = 2"
    assert cleaned.count("\n") == raw.replace("\r\n", "\n").count("\n")  # same number of lines
