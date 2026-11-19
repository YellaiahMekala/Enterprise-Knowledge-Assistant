# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""Upload sniffing: the bytes must match the name and the declared type (TDD 4.3)."""

import pytest

from eka.domain.errors import PayloadTooLarge, UnsupportedMedia
from eka.domain.models import FileKind
from eka.ingestion.sniff import (
    DOCX_CONTENT_TYPE,
    Sniffed,
    clean_filename,
    extension_of,
    sniff,
)
from tests.files import make_docx, make_many_entries_docx, make_pdf, make_zip_bomb_docx

TEXT_EXTENSIONS = (".java", ".md", ".txt")


def run(filename: str, declared: str | None, data: bytes, max_text: int = 1024) -> Sniffed:
    return sniff(filename, declared, data, text_extensions=TEXT_EXTENSIONS, max_text_bytes=max_text)


def test_a_real_pdf_is_accepted_and_typed_by_its_bytes() -> None:
    result = run("policy.pdf", "application/pdf", make_pdf(["hello"]))
    assert result.kind is FileKind.PDF
    assert result.content_type == "application/pdf"


def test_a_real_docx_is_accepted() -> None:
    result = run("a.docx", DOCX_CONTENT_TYPE, make_docx([("Normal", "hi")]))
    assert result.kind is FileKind.DOCX


def test_csv_and_text_files_are_accepted() -> None:
    assert run("rows.csv", "text/csv", b"a,b\n1,2\n").kind is FileKind.CSV
    assert run("Main.java", "text/x-java-source", b"class A {}").kind is FileKind.TEXT
    assert run("notes.md", None, b"# Title").kind is FileKind.TEXT


@pytest.mark.parametrize("declared", [None, "", "application/octet-stream"])
def test_a_generic_or_missing_declared_type_is_not_a_reason_to_reject(declared: str | None) -> None:
    assert run("a.pdf", declared, make_pdf(["x"])).kind is FileKind.PDF


def test_an_executable_renamed_pdf_is_rejected() -> None:
    with pytest.raises(UnsupportedMedia) as error:
        run("evil.pdf", "application/pdf", b"MZ\x90\x00 not a pdf")
    assert error.value.reason == "type_mismatch"


def test_the_pdf_signature_must_be_near_the_start() -> None:
    with pytest.raises(UnsupportedMedia):
        run("late.pdf", None, b"x" * 2000 + b"%PDF-1.4")


def test_a_declared_type_that_contradicts_the_extension_is_rejected() -> None:
    with pytest.raises(UnsupportedMedia) as error:
        run("a.pdf", "text/html", make_pdf(["x"]))
    assert error.value.reason == "type_mismatch"


def test_an_unknown_extension_is_unsupported() -> None:
    with pytest.raises(UnsupportedMedia) as error:
        run("tool.exe", "application/octet-stream", b"MZ")
    assert error.value.reason == "unsupported_type"


def test_a_binary_file_renamed_to_java_is_rejected() -> None:
    with pytest.raises(UnsupportedMedia) as error:
        run("Fake.java", "text/plain", b"class\x00\x01\x02")
    assert error.value.reason == "type_mismatch"


@pytest.mark.parametrize("name", ["bad.csv", "bad.java"])
def test_text_that_is_not_utf8_is_rejected_without_guessing(name: str) -> None:
    with pytest.raises(UnsupportedMedia) as error:
        run(name, None, "café".encode("latin-1"))
    assert error.value.reason == "unsupported_encoding"


def test_a_utf8_bom_is_allowed() -> None:
    assert run("rows.csv", None, b"\xef\xbb\xbfa,b\n1,2").kind is FileKind.CSV


def test_an_oversized_text_file_is_payload_too_large() -> None:
    with pytest.raises(PayloadTooLarge):
        run("big.txt", None, b"a" * 2000, max_text=1000)


def test_a_zip_that_is_not_a_docx_is_rejected() -> None:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("hello.txt", "hi")
    with pytest.raises(UnsupportedMedia) as error:
        run("a.docx", None, buffer.getvalue())
    assert error.value.reason == "type_mismatch"


def test_random_bytes_named_docx_are_rejected() -> None:
    with pytest.raises(UnsupportedMedia):
        run("a.docx", None, b"not a zip at all")


def test_a_zip_bomb_is_rejected_from_the_directory_alone() -> None:
    with pytest.raises(UnsupportedMedia) as error:
        run("bomb.docx", None, make_zip_bomb_docx())
    assert error.value.reason == "invalid_archive"


def test_a_docx_with_thousands_of_entries_is_rejected() -> None:
    with pytest.raises(UnsupportedMedia) as error:
        run("many.docx", None, make_many_entries_docx())
    assert error.value.reason == "invalid_archive"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("report.pdf", "report.pdf"),
        ("..\\..\\windows\\system32\\evil.pdf", "evil.pdf"),
        ("/etc/passwd", "passwd"),
        ("a/b/../c.docx", "c.docx"),
        ("na\x00me\x07.pdf", "name.pdf"),
        ("", "upload"),
        (None, "upload"),
        ("   ", "upload"),
        ("x" * 400 + ".pdf", ("x" * 400 + ".pdf")[:255]),
    ],
)
def test_filenames_are_reduced_to_a_safe_display_name(raw: str | None, expected: str) -> None:
    assert clean_filename(raw) == expected


def test_extension_is_lower_cased() -> None:
    assert extension_of("REPORT.PDF") == ".pdf"
    assert extension_of("noextension") == ""
