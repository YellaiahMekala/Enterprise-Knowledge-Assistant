"""Plain data types shared by every layer. No framework, no I/O."""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

# One rule for what a user id may look like. The database repeats it as a CHECK constraint.
USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,36}$")


def is_valid_user_id(value: str) -> bool:
    return USER_ID_PATTERN.fullmatch(value) is not None


class Role(StrEnum):
    USER = "user"
    ADMIN = "admin"


class DocumentStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class NewDocument:
    """What the upload path knows before the row exists. The caller chooses the id because
    the storage key (``{owner_id}/{id}``) is derived from it."""

    id: UUID
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    storage_key: str


@dataclass(frozen=True, slots=True)
class Document:
    id: UUID
    owner_id: str
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    storage_key: str
    status: DocumentStatus
    error_code: str | None
    attempts: int
    page_count: int | None
    chunk_count: int | None
    created_at: datetime
    updated_at: datetime


class FileKind(StrEnum):
    """What an upload really is, decided from its bytes (not from its name)."""

    PDF = "pdf"
    DOCX = "docx"
    CSV = "csv"
    TEXT = "text"  # code and plain-text files (.java, .md, .txt, ...)


@dataclass(frozen=True, slots=True)
class Segment:
    """A piece of a document that a citation can point to exactly: a page, a section, a row group
    or a block of lines. Chunks never cross a segment boundary (ADR-007).

    ``locator`` is a typed dict: ``{"type": "page", "page": 3}``, ``{"type": "section", ...}``,
    ``{"type": "rows", ...}`` or ``{"type": "lines", "path": ..., "start": 1, "end": 40}``.
    ``unit`` says how the chunker may split it: prose (paragraphs, sentences) or code (lines).
    """

    text: str
    locator: Mapping[str, Any]
    unit: Literal["prose", "lines"] = "prose"


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    segments: tuple[Segment, ...]
    page_count: int | None


@dataclass(frozen=True, slots=True)
class ParseLimits:
    max_pages: int = 500
    max_csv_rows: int = 50_000
    max_text_bytes: int = 512 * 1024


@dataclass(frozen=True, slots=True)
class Chunk:
    """One embeddable passage. ``text`` is exactly ``segment_text[char_start:char_end]``."""

    ordinal: int
    text: str
    locator: Mapping[str, Any]
    char_start: int
    char_end: int
    token_count: int


@dataclass(frozen=True, slots=True)
class NewChunk:
    """A chunk with its vector, ready to store."""

    chunk: Chunk
    embedding: Sequence[float]


@dataclass(frozen=True, slots=True)
class ClaimedDocument:
    """What the worker needs about a document it has claimed (it works across owners)."""

    id: UUID
    owner_id: str
    filename: str
    content_type: str
    storage_key: str
    attempts: int
