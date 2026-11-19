# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""Decide what an upload really is from its bytes (TDD 4.3).

The file name and the declared content type must agree with the bytes, otherwise the upload is
rejected with 415. No ``libmagic``: each type has a small, explicit check.
"""

import io
import re
import unicodedata
import zipfile
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import PurePosixPath

from eka.domain.errors import PayloadTooLarge, UnsupportedMedia
from eka.domain.models import FileKind

PDF_CONTENT_TYPE = "application/pdf"
DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
CSV_CONTENT_TYPE = "text/csv"
TEXT_CONTENT_TYPE = "text/plain"

_PDF_MAGIC = b"%PDF-"
_PDF_MAGIC_WINDOW = 1024
# Zip-bomb guards for DOCX: the central directory is read without decompressing anything.
_MAX_ZIP_ENTRIES = 2_000
_MAX_ZIP_EXPANDED_BYTES = 200 * 1024 * 1024
_MAX_ZIP_RATIO = 200
_DOCX_REQUIRED = ("[Content_Types].xml", "word/document.xml")

_GENERIC_TYPES = {"", "application/octet-stream", "binary/octet-stream"}
_DECLARED_OK = {
    FileKind.PDF: {PDF_CONTENT_TYPE},
    FileKind.DOCX: {DOCX_CONTENT_TYPE},
    # Browsers and spreadsheet tools label CSV files in several ways.
    FileKind.CSV: {"text/csv", "application/csv", "application/vnd.ms-excel", "text/plain"},
}
_TEXT_EXTRA_TYPES = {
    "application/json",
    "application/xml",
    "application/x-yaml",
    "application/yaml",
    "application/sql",
    "application/x-sql",
    "application/x-sh",
}
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True, slots=True)
class Sniffed:
    kind: FileKind
    content_type: str  # canonical type stored with the document


def clean_filename(name: str | None) -> str:
    """A safe display name: no path parts, no control characters, at most 255 characters.
    It is stored for display only and never used to build a storage path."""
    base = PurePosixPath((name or "").replace("\\", "/")).name
    base = unicodedata.normalize("NFC", _CONTROL.sub("", base)).strip()
    return base[:255] or "upload"


def extension_of(filename: str) -> str:
    return PurePosixPath(filename).suffix.lower()


def _declared_ok(kind: FileKind, declared: str | None) -> bool:
    value = (declared or "").split(";")[0].strip().lower()
    if value in _GENERIC_TYPES:
        return True
    if kind is FileKind.TEXT:
        return value.startswith("text/") or value in _TEXT_EXTRA_TYPES
    return value in _DECLARED_OK[kind]


def _check_utf8_text(data: bytes) -> None:
    if b"\x00" in data:
        raise UnsupportedMedia("type_mismatch")
    try:
        data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise UnsupportedMedia("unsupported_encoding") from None


def _check_docx(data: bytes) -> None:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise UnsupportedMedia("type_mismatch") from None
    with archive:
        infos = archive.infolist()
        names = {info.filename for info in infos}
        if not all(name in names for name in _DOCX_REQUIRED):
            raise UnsupportedMedia("type_mismatch")
        expanded = sum(info.file_size for info in infos)
        packed = max(1, sum(info.compress_size for info in infos))
        if (
            len(infos) > _MAX_ZIP_ENTRIES
            or expanded > _MAX_ZIP_EXPANDED_BYTES
            or expanded / packed > _MAX_ZIP_RATIO
        ):
            raise UnsupportedMedia("invalid_archive")


def sniff(
    filename: str,
    declared_content_type: str | None,
    data: bytes,
    *,
    text_extensions: Collection[str],
    max_text_bytes: int,
) -> Sniffed:
    """Return the real kind, or raise ``UnsupportedMedia`` / ``PayloadTooLarge``."""
    extension = extension_of(filename)
    if extension == ".pdf":
        kind = FileKind.PDF
    elif extension == ".docx":
        kind = FileKind.DOCX
    elif extension == ".csv":
        kind = FileKind.CSV
    elif extension in text_extensions:
        kind = FileKind.TEXT
    else:
        raise UnsupportedMedia("unsupported_type")

    if not _declared_ok(kind, declared_content_type):
        raise UnsupportedMedia("type_mismatch")

    if kind is FileKind.PDF:
        if _PDF_MAGIC not in data[:_PDF_MAGIC_WINDOW]:
            raise UnsupportedMedia("type_mismatch")
        return Sniffed(kind, PDF_CONTENT_TYPE)
    if kind is FileKind.DOCX:
        _check_docx(data)
        return Sniffed(kind, DOCX_CONTENT_TYPE)
    if kind is FileKind.CSV:
        _check_utf8_text(data)
        return Sniffed(kind, CSV_CONTENT_TYPE)
    if len(data) > max_text_bytes:
        raise PayloadTooLarge()
    _check_utf8_text(data)
    return Sniffed(kind, TEXT_CONTENT_TYPE)
