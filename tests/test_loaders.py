"""Loaders and the parse entry point: locators must point at the real place in the file."""

import pytest

from eka.domain.errors import PermanentIngestionError
from eka.domain.models import ParsedDocument, ParseLimits
from eka.ingestion.loaders.csv_file import load_csv
from eka.ingestion.loaders.docx_file import load_docx
from eka.ingestion.loaders.pdf_file import load_pdf
from eka.ingestion.loaders.text_file import TARGET_LINES, load_text
from eka.ingestion.parse import parse_document
from tests.files import JAVA_SAMPLE, make_docx, make_encrypted_pdf, make_pdf

LIMITS = ParseLimits(max_pages=5, max_csv_rows=10, max_text_bytes=100_000)
TEXT_EXTENSIONS = (".java", ".md", ".txt", ".sql")


def code_of(error: pytest.ExceptionInfo[PermanentIngestionError]) -> str:
    return error.value.code


# ----------------------------------------------------------------------------- PDF


def test_pdf_gives_one_segment_per_page_with_a_one_based_page_locator() -> None:
    segments, pages = load_pdf(make_pdf(["First page text", "Second page text"]), LIMITS)
    assert pages == 2
    assert [s.locator for s in segments] == [
        {"type": "page", "page": 1},
        {"type": "page", "page": 2},
    ]
    assert "First page" in segments[0].text
    assert "Second page" in segments[1].text


def test_pdf_pages_without_text_are_skipped_but_still_counted() -> None:
    segments, pages = load_pdf(make_pdf(["Has text", "", "Also text"]), LIMITS)
    assert pages == 3
    assert [s.locator["page"] for s in segments] == [1, 3]


def test_an_encrypted_pdf_fails_as_encrypted() -> None:
    with pytest.raises(PermanentIngestionError) as error:
        load_pdf(make_encrypted_pdf(), LIMITS)
    assert code_of(error) == "encrypted"


def test_a_truncated_pdf_fails_as_corrupt() -> None:
    data = make_pdf(["some text here"])
    with pytest.raises(PermanentIngestionError) as error:
        load_pdf(data[: len(data) // 3], LIMITS)
    assert code_of(error) == "corrupt"


def test_garbage_after_a_pdf_header_fails_as_corrupt() -> None:
    with pytest.raises(PermanentIngestionError) as error:
        load_pdf(b"%PDF-1.4\nthis is not a document", LIMITS)
    assert code_of(error) == "corrupt"


def test_a_pdf_over_the_page_cap_fails_as_too_large() -> None:
    with pytest.raises(PermanentIngestionError) as error:
        load_pdf(make_pdf(["x"] * 6), LIMITS)
    assert code_of(error) == "too_large"


# ----------------------------------------------------------------------------- DOCX


def test_docx_sections_follow_headings_with_a_path_and_paragraph_range() -> None:
    data = make_docx(
        [
            ("Normal", "Preface line."),
            ("Heading 1", "Leave"),
            ("Normal", "Staff get 25 days."),
            ("Heading 2", "Carry-over"),
            ("Normal", "Up to five days carry over."),
            ("Normal", "They expire in March."),
            ("Heading 1", "Travel"),
            ("Normal", "Book through the portal."),
        ]
    )
    segments = load_docx(data)
    locators = [s.locator for s in segments]
    assert locators[0] == {"type": "section", "path": [], "paragraphs": [1, 1]}
    assert locators[1] == {"type": "section", "path": ["Leave"], "paragraphs": [2, 3]}
    assert locators[2] == {"type": "section", "path": ["Leave", "Carry-over"], "paragraphs": [4, 6]}
    assert locators[3] == {"type": "section", "path": ["Travel"], "paragraphs": [7, 8]}
    assert "expire in March" in segments[2].text
    assert segments[2].text.startswith("Carry-over")  # the heading text travels with its section


def test_docx_tables_are_flattened_row_by_row_in_body_order() -> None:
    data = make_docx(
        [("Heading 1", "Rates"), ("Normal", "See below.")],
        table=[["Grade", "Days"], ["Junior", "20"], ["Senior", "25"]],
    )
    (segment,) = load_docx(data)
    assert "Grade | Days" in segment.text
    assert "Senior | 25" in segment.text
    assert segment.locator["paragraphs"] == [1, 5]


def test_a_docx_that_is_not_a_zip_fails_as_corrupt() -> None:
    with pytest.raises(PermanentIngestionError) as error:
        load_docx(b"not a docx")
    assert code_of(error) == "corrupt"


# ----------------------------------------------------------------------------- CSV


def test_csv_rows_are_rendered_with_their_column_names_and_numbered_from_one() -> None:
    data = b"name,city\nAda,London\nGrace,New York\n"
    (segment,) = load_csv(data, LIMITS)
    assert segment.text == "name=Ada | city=London\nname=Grace | city=New York"
    assert segment.locator == {"type": "rows", "start": 1, "end": 2}


def test_csv_blank_rows_keep_their_numbers_but_add_no_text() -> None:
    (segment,) = load_csv(b"a,b\n1,2\n,\n3,4\n", LIMITS)
    assert segment.locator == {"type": "rows", "start": 1, "end": 3}
    assert segment.text.count("\n") == 1


def test_csv_ragged_rows_and_blank_headers_do_not_break_rendering() -> None:
    (segment,) = load_csv(b"a,,c\n1\n2,3,4,5\n", LIMITS)
    assert "a=1" in segment.text
    assert "column_2=3" in segment.text


def test_a_long_csv_is_split_into_groups_with_contiguous_row_ranges() -> None:
    rows = "\n".join(f"{i},{'x' * 200}" for i in range(1, 11))
    segments = load_csv(f"id,payload\n{rows}\n".encode(), LIMITS)
    assert len(segments) > 1
    ranges = [(s.locator["start"], s.locator["end"]) for s in segments]
    assert ranges[0][0] == 1 and ranges[-1][1] == 10
    assert all(b[0] == a[1] + 1 for a, b in zip(ranges, ranges[1:], strict=False))


def test_a_csv_over_the_row_cap_fails_as_too_large() -> None:
    data = ("a\n" + "\n".join(str(i) for i in range(11))).encode()
    with pytest.raises(PermanentIngestionError) as error:
        load_csv(data, LIMITS)
    assert code_of(error) == "too_large"


def test_an_empty_csv_has_no_segments() -> None:
    assert load_csv(b"", LIMITS) == []


# ----------------------------------------------------------------------------- code and text


def test_java_blocks_split_at_members_and_keep_braces_in_strings_and_comments_inert() -> None:
    segments = load_text(JAVA_SAMPLE.encode(), "Greeter.java")
    lines = JAVA_SAMPLE.split("\n")
    for segment in segments:
        loc = segment.locator
        assert loc["type"] == "lines" and loc["path"] == "Greeter.java"
        assert segment.text == "\n".join(lines[loc["start"] - 1 : loc["end"]])
    # The greet() method has a blank-free body but braces inside a string and a comment; it must
    # be inside one segment together with its signature and its return statement.
    holder = next(s for s in segments if "public String greet" in s.text)
    assert 'return "Hello, " + name + brace;' in holder.text
    assert all(s.unit == "lines" for s in segments)


def test_java_blank_lines_inside_a_method_do_not_cut_it() -> None:
    body = "\n".join(f"        step{i}();" for i in range(5))
    source = f"class A {{\n    void run() {{\n{body}\n\n{body}\n    }}\n}}\n"
    segments = load_text(source.encode(), "A.java")
    assert len([s for s in segments if "void run()" in s.text]) == 1
    holder = next(s for s in segments if "void run()" in s.text)
    assert holder.text.count("step0();") == 2  # both halves of the method are together


def test_small_members_are_merged_but_a_large_block_stands_alone() -> None:
    small = "\n\n".join(f"int a{i};" for i in range(6))
    big = "\n".join(f"line{i};" for i in range(TARGET_LINES + 20))
    segments = load_text(f"{small}\n\n{big}\n".encode(), "Many.sql")
    assert segments[0].text.count("int a") == 6  # six tiny blocks, one segment
    assert max(s.locator["end"] - s.locator["start"] + 1 for s in segments) > TARGET_LINES


def test_markdown_headings_start_new_blocks_and_fences_are_respected() -> None:
    source = "# One\ntext\n\n```\n# not a heading\n```\n\n# Two\nmore\n"
    segments = load_text(source.encode(), "n.md")
    joined = "\n".join(s.text for s in segments)
    assert "# not a heading" in joined
    assert all(s.unit == "prose" for s in segments)  # notes are chunked as prose


def test_crlf_line_endings_give_the_same_line_numbers() -> None:
    unix = load_text(b"a\nb\n\nc\n", "x.txt")
    windows = load_text(b"a\r\nb\r\n\r\nc\r\n", "x.txt")
    assert [s.locator for s in unix] == [s.locator for s in windows]


def test_text_that_is_not_utf8_fails() -> None:
    with pytest.raises(PermanentIngestionError) as error:
        load_text("café".encode("latin-1"), "a.txt")
    assert code_of(error) == "unsupported_encoding"


# ----------------------------------------------------------------------------- parse entry point


def parse(filename: str, data: bytes, declared: str | None = None) -> ParsedDocument:
    return parse_document(filename, declared, data, text_extensions=TEXT_EXTENSIONS, limits=LIMITS)


def test_parse_cleans_prose_but_keeps_code_lines_intact() -> None:
    prose = parse("p.pdf", make_pdf(["inter-\nnational   law"]))
    assert prose.segments[0].text == "international law"
    assert prose.page_count == 1

    code = parse("A.java", JAVA_SAMPLE.encode())
    assert code.page_count is None
    assert any("    private final String name;" in s.text for s in code.segments)  # indentation


def test_parse_sniffs_again_and_maps_failures_to_fixed_codes() -> None:
    with pytest.raises(PermanentIngestionError) as error:
        parse("fake.pdf", b"MZ not a pdf")
    assert code_of(error) == "corrupt"
    with pytest.raises(PermanentIngestionError) as error:
        parse("bad.csv", "café".encode("latin-1"))
    assert code_of(error) == "unsupported_encoding"
    with pytest.raises(PermanentIngestionError) as error:
        parse("big.txt", b"a" * 200_000)
    assert code_of(error) == "too_large"


def test_a_document_with_no_text_fails_as_no_text() -> None:
    with pytest.raises(PermanentIngestionError) as error:
        parse("blank.pdf", make_pdf(["", ""]))
    assert code_of(error) == "no_text"
    with pytest.raises(PermanentIngestionError) as error:
        parse("empty.txt", b"\n\n   \n")
    assert code_of(error) == "no_text"
