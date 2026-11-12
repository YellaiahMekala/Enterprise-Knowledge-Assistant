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
    # Set only for a page stored by the web fallback (ADR-030).
    source_url: str | None = None
    fetched_at: datetime | None = None


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
    source_url: str | None = None
    fetched_at: datetime | None = None


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


@dataclass(frozen=True, slots=True)
class SearchFilters:
    """Optional search restrictions. An empty field means no restriction."""

    document_ids: tuple[UUID, ...] = ()
    content_types: tuple[str, ...] = ()
    uploaded_after: datetime | None = None
    uploaded_before: datetime | None = None

    @property
    def is_empty(self) -> bool:
        return not (
            self.document_ids or self.content_types or self.uploaded_after or self.uploaded_before
        )


@dataclass(frozen=True, slots=True)
class Candidate:
    """One chunk from a single search path. ``score`` is a cosine distance for the dense path
    (smaller is closer) and a text rank for the sparse path (larger is closer)."""

    chunk_id: UUID
    document_id: UUID
    text: str
    locator: Mapping[str, Any]
    score: float


@dataclass(frozen=True, slots=True)
class DocumentInfo:
    """What a search result shows about its document."""

    filename: str
    content_type: str
    source_url: str | None = None
    fetched_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class SearchHit:
    """A ranked result. ``cosine`` is the question-to-chunk similarity, always set."""

    rank: int
    chunk_id: UUID
    document_id: UUID
    filename: str
    locator: Mapping[str, Any]
    text: str
    fused: float
    cosine: float
    source_url: str | None = None
    fetched_at: datetime | None = None


# --- answering (phase P4) ------------------------------------------------------------------------

ChatRole = Literal["system", "user", "assistant"]
AnswerMode = Literal["verified", "fast"]


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """One message sent to the chat model."""

    role: ChatRole
    content: str


@dataclass(frozen=True, slots=True)
class Citation:
    """A passage an answer relies on. ``index`` is the number used in the answer text, as in
    ``[2]``. It is resolved on the server from the retrieved passages, not taken from the model."""

    index: int
    chunk_id: UUID
    document_id: UUID
    filename: str
    locator: Mapping[str, Any]
    quote: str
    # A web citation (ADR-030) carries the page address and when it was fetched.
    source_url: str | None = None
    fetched_at: datetime | None = None

    @property
    def kind(self) -> Literal["document", "web"]:
        return "web" if self.source_url else "document"


@dataclass(frozen=True, slots=True)
class Conversation:
    id: UUID
    owner_id: str
    title: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class StoredMessage:
    id: UUID
    conversation_id: UUID
    role: Literal["user", "assistant"]
    content: str
    citations: tuple[Citation, ...]
    refused: bool
    refusal_reason: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class UsageEvent:
    """What one answer cost. Counts and timings only, never text."""

    conversation_id: UUID | None
    mode: str
    model: str
    refused: bool
    retrieved: int
    top_cosine: float | None
    prompt_chars: int
    completion_chars: int
    latency_ms: int
    provider: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    token_source: str | None = None  # "provider" or "estimated"
    cost_usd: float | None = None
    ttft_ms: int | None = None  # request start to the first model fragment
    answer_ttfb_ms: int | None = None  # request start to the first text sent to the client


@dataclass(frozen=True, slots=True)
class UsageRow:
    """One line of the admin usage report: one user or one day (ADR-037). No text."""

    key: str
    requests: int
    refused: int
    prompt_tokens: int | None  # None when no event in the group has counts (before migration 0004)
    completion_tokens: int | None
    cost_usd: float | None
    latency_p50_ms: int | None
    latency_p95_ms: int | None
    ttft_p50_ms: int | None
    ttft_p95_ms: int | None


@dataclass(slots=True)
class TokenUsage:
    """Filled by a chat adapter during one or more calls (ADR-037). ``model`` and ``provider`` are
    those of the last model that answered."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated: bool = False
    calls: int = 0
    model: str | None = None
    provider: str | None = None

    def add(
        self, model: str, provider: str, prompt: int, completion: int, *, estimated: bool = False
    ) -> None:
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.estimated = self.estimated or estimated
        self.calls += 1
        self.model = model
        self.provider = provider


@dataclass(frozen=True, slots=True)
class WebPage:
    """A page fetched by the web fallback. ``url`` is the final address after redirects."""

    url: str
    content_type: str
    text: str
