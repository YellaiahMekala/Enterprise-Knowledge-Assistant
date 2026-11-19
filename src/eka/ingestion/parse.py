# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""One entry point from bytes to cleaned segments (TDD 4.3). Runs inside the parse child process."""

from collections.abc import Collection

from eka.domain.errors import (
    CORRUPT,
    NO_TEXT,
    TOO_LARGE,
    UNSUPPORTED_ENCODING,
    PayloadTooLarge,
    PermanentIngestionError,
    UnsupportedMedia,
)
from eka.domain.models import FileKind, ParsedDocument, ParseLimits, Segment
from eka.ingestion.cleaning import clean_lines, clean_prose
from eka.ingestion.loaders.csv_file import load_csv
from eka.ingestion.loaders.docx_file import load_docx
from eka.ingestion.loaders.pdf_file import load_pdf
from eka.ingestion.loaders.text_file import load_text
from eka.ingestion.sniff import sniff


def parse_document(
    filename: str,
    declared_content_type: str | None,
    data: bytes,
    *,
    text_extensions: Collection[str],
    limits: ParseLimits,
) -> ParsedDocument:
    """Sniff again (the worker never assumes an earlier check happened), load, clean.

    Raises ``PermanentIngestionError`` with a fixed code when the file can never be ingested.
    """
    try:
        sniffed = sniff(
            filename,
            declared_content_type,
            data,
            text_extensions=text_extensions,
            max_text_bytes=limits.max_text_bytes,
        )
    except UnsupportedMedia as error:
        code = UNSUPPORTED_ENCODING if error.reason == "unsupported_encoding" else CORRUPT
        raise PermanentIngestionError(code) from error
    except PayloadTooLarge as error:
        raise PermanentIngestionError(TOO_LARGE) from error

    page_count: int | None = None
    if sniffed.kind is FileKind.PDF:
        raw, page_count = load_pdf(data, limits)
    elif sniffed.kind is FileKind.DOCX:
        raw = load_docx(data)
    elif sniffed.kind is FileKind.CSV:
        raw = load_csv(data, limits)
    else:
        raw = load_text(data, filename)

    cleaned: list[Segment] = []
    for segment in raw:
        if segment.locator.get("type") == "lines":
            text = clean_lines(segment.text)
        else:
            text = clean_prose(segment.text)
        if text.strip():
            cleaned.append(Segment(text, segment.locator, segment.unit))
    if not cleaned:
        raise PermanentIngestionError(NO_TEXT)
    return ParsedDocument(tuple(cleaned), page_count)
