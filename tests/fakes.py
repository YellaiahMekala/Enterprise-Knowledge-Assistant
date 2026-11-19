# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""In-memory test doubles for the ports (Test Strategy section 4). They are deliberately simple
but honour each port's contract (owner scoping, idempotent delete), so service and API tests
exercise real behaviour without a database."""

import asyncio
import hashlib
import math
import re
import uuid
from collections.abc import AsyncGenerator, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from eka.domain.errors import EkaError, Unavailable
from eka.domain.models import (
    Candidate,
    ChatMessage,
    Citation,
    ClaimedDocument,
    Conversation,
    Document,
    DocumentInfo,
    DocumentStatus,
    NewChunk,
    NewDocument,
    SearchFilters,
    StoredMessage,
    TokenUsage,
    UsageEvent,
)

_WORD = re.compile(r"\w+|[^\w\s]")


class FakeEmbedder:
    """Deterministic vectors from hashed word features, L2-normalised, 384 dimensions, no model
    download. ``count_tokens`` counts words and punctuation, so chunk sizes are predictable."""

    model_name = "fake-embedder"
    dimension = 384

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def count_tokens(self, text: str) -> int:
        return len(_WORD.findall(text))

    def _vector(self, text: str) -> list[float]:
        values = [0.0] * self.dimension
        for word in _WORD.findall(text.lower()):
            digest = hashlib.sha256(word.encode()).digest()
            values[int.from_bytes(digest[:4], "big") % self.dimension] += 1.0
        norm = math.sqrt(sum(v * v for v in values)) or 1.0
        return [v / norm for v in values]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


class InMemoryFileStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.fail_put = False
        self.fail_get = False

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        if self.fail_put:
            raise Unavailable("put failed")
        self.objects[key] = data

    async def get(self, key: str) -> bytes:
        if self.fail_get or key not in self.objects:
            raise Unavailable("get failed")
        return self.objects[key]

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)


class InMemoryDocumentRepository:
    """Owner-scoped like the real one: every lookup filters by ``owner_id``."""

    def __init__(self) -> None:
        self.rows: dict[UUID, Document] = {}
        self.fail_add_after_insert = False

    def _now(self) -> datetime:
        return datetime.now(UTC)

    async def add(self, owner_id: str, new: NewDocument) -> tuple[Document, bool]:
        for row in self.rows.values():
            if row.owner_id == owner_id and row.sha256 == new.sha256:
                return row, False
        if self.fail_add_after_insert:
            raise RuntimeError("database failed")
        now = self._now()
        document = Document(
            id=new.id,
            owner_id=owner_id,
            filename=new.filename,
            content_type=new.content_type,
            size_bytes=new.size_bytes,
            sha256=new.sha256,
            storage_key=new.storage_key,
            status=DocumentStatus.PENDING,
            error_code=None,
            attempts=0,
            page_count=None,
            chunk_count=None,
            created_at=now,
            updated_at=now,
            source_url=new.source_url,
            fetched_at=new.fetched_at,
        )
        self.rows[new.id] = document
        return document, True

    async def get(self, owner_id: str, document_id: UUID) -> Document | None:
        row = self.rows.get(document_id)
        return row if row is not None and row.owner_id == owner_id else None

    async def get_by_sha256(self, owner_id: str, sha256: str) -> Document | None:
        for row in self.rows.values():
            if row.owner_id == owner_id and row.sha256 == sha256:
                return row
        return None

    async def web_copies(self, owner_id: str, source_url: str) -> list[Document]:
        rows = [
            row
            for row in self.rows.values()
            if row.owner_id == owner_id and row.source_url == source_url
        ]
        return sorted(rows, key=lambda r: r.fetched_at or r.created_at, reverse=True)

    async def count_by_owner(self, owner_id: str) -> int:
        return sum(1 for row in self.rows.values() if row.owner_id == owner_id)

    async def list_by_owner(
        self,
        owner_id: str,
        *,
        status: DocumentStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Document]:
        rows = [
            row
            for row in self.rows.values()
            if row.owner_id == owner_id and (status is None or row.status is status)
        ]
        rows.sort(key=lambda r: r.created_at, reverse=True)
        return rows[offset : offset + limit]

    async def delete(self, owner_id: str, document_id: UUID) -> bool:
        row = self.rows.get(document_id)
        if row is None or row.owner_id != owner_id:
            return False
        del self.rows[document_id]
        return True


class InMemoryQueue:
    """The worker's queue over the same rows, recording what the processor did to them."""

    def __init__(self, repository: InMemoryDocumentRepository) -> None:
        self._repository = repository
        self.chunks: dict[UUID, list[NewChunk]] = {}
        self.completed_page_counts: dict[UUID, int | None] = {}
        self.released: list[UUID] = []
        self.complete_returns = True

    async def claim(self, *, stale_minutes: int, max_attempts: int) -> ClaimedDocument | None:
        pending = [r for r in self._repository.rows.values() if r.status is DocumentStatus.PENDING]
        if not pending:
            return None
        row = min(pending, key=lambda r: r.created_at)
        claimed = replace(row, status=DocumentStatus.PROCESSING, attempts=row.attempts + 1)
        self._repository.rows[row.id] = claimed
        return ClaimedDocument(
            id=row.id,
            owner_id=row.owner_id,
            filename=row.filename,
            content_type=row.content_type,
            storage_key=row.storage_key,
            attempts=claimed.attempts,
        )

    async def complete(
        self,
        document_id: UUID,
        chunks: Sequence[NewChunk],
        *,
        page_count: int | None,
        embedding_model: str,
        chunk_config: str,
    ) -> bool:
        if not self.complete_returns or document_id not in self._repository.rows:
            return False
        row = self._repository.rows[document_id]
        self._repository.rows[document_id] = replace(
            row, status=DocumentStatus.READY, chunk_count=len(chunks), page_count=page_count
        )
        self.chunks[document_id] = list(chunks)
        self.completed_page_counts[document_id] = page_count
        return True

    async def fail(self, document_id: UUID, error_code: str) -> None:
        row = self._repository.rows[document_id]
        self._repository.rows[document_id] = replace(
            row, status=DocumentStatus.FAILED, error_code=error_code
        )

    async def release(self, document_id: UUID, *, max_attempts: int) -> None:
        row = self._repository.rows[document_id]
        exhausted = row.attempts >= max_attempts
        self._repository.rows[document_id] = replace(
            row,
            status=DocumentStatus.FAILED if exhausted else DocumentStatus.PENDING,
            error_code="max_attempts" if exhausted else None,
        )
        self.released.append(document_id)


class InMemoryChunkSearch:
    """The retrieval port over lists: brute-force cosine, and term-count scoring for sparse."""

    def __init__(self) -> None:
        # document id -> (owner, filename, content type, created at)
        self.documents: dict[UUID, tuple[str, str, str, datetime]] = {}
        self.web_sources: dict[UUID, tuple[str, datetime]] = {}
        self.chunks: list[dict[str, Any]] = []
        self.exact_flags: list[bool] = []

    def add_document(
        self,
        owner: str,
        document_id: UUID,
        filename: str,
        *,
        content_type: str = "text/plain",
        created_at: datetime | None = None,
        source_url: str | None = None,
    ) -> None:
        when = created_at or datetime(2026, 11, 1, tzinfo=UTC)
        self.documents[document_id] = (owner, filename, content_type, when)
        if source_url is not None:
            self.web_sources[document_id] = (source_url, when)

    def add_chunk(
        self, owner: str, document_id: UUID, text: str, vector: list[float], ordinal: int = 0
    ) -> UUID:
        chunk_id = uuid.uuid4()
        self.chunks.append(
            {
                "id": chunk_id,
                "owner": owner,
                "document_id": document_id,
                "text": text,
                "terms": set(re.findall(r"\w+", text.lower())),
                "vector": vector,
                "locator": {"type": "page", "page": ordinal + 1},
            }
        )
        return chunk_id

    def _owned(self, owner: str, document_ids: list[UUID] | None) -> list[dict[str, Any]]:
        return [
            c
            for c in self.chunks
            if c["owner"] == owner and (document_ids is None or c["document_id"] in document_ids)
        ]

    async def count_chunks(self, owner_id: str) -> int:
        return sum(1 for c in self.chunks if c["owner"] == owner_id)

    async def resolve_documents(self, owner_id: str, filters: SearchFilters) -> list[UUID] | None:
        if filters.is_empty:
            return None
        found = []
        for document_id, (owner, _name, content_type, when) in self.documents.items():
            if owner != owner_id:
                continue
            if filters.document_ids and document_id not in filters.document_ids:
                continue
            if filters.content_types and content_type not in filters.content_types:
                continue
            if filters.uploaded_after and when < filters.uploaded_after:
                continue
            if filters.uploaded_before and when >= filters.uploaded_before:
                continue
            found.append(document_id)
        return found

    async def dense(
        self,
        owner_id: str,
        vector: Sequence[float],
        limit: int,
        *,
        document_ids: list[UUID] | None,
        exact: bool,
        ef_search: int,
    ) -> list[Candidate]:
        self.exact_flags.append(exact)
        scored = [
            Candidate(
                c["id"],
                c["document_id"],
                c["text"],
                c["locator"],
                1.0 - _cosine(vector, c["vector"]),
            )
            for c in self._owned(owner_id, document_ids)
        ]
        scored.sort(key=lambda candidate: candidate.score)
        return scored[:limit]

    async def sparse(
        self,
        owner_id: str,
        query: str,
        limit: int,
        *,
        document_ids: list[UUID] | None,
    ) -> list[Candidate]:
        terms = {t for t in query.split(" | ") if t}
        scored = []
        for c in self._owned(owner_id, document_ids):
            hits = len(terms & c["terms"])
            if hits:
                scored.append(
                    Candidate(c["id"], c["document_id"], c["text"], c["locator"], float(hits))
                )
        scored.sort(key=lambda candidate: -candidate.score)
        return scored[:limit]

    async def cosine(
        self, owner_id: str, vector: Sequence[float], chunk_ids: Sequence[UUID]
    ) -> dict[UUID, float]:
        return {
            c["id"]: _cosine(vector, c["vector"])
            for c in self._owned(owner_id, None)
            if c["id"] in chunk_ids
        }

    async def document_info(
        self, owner_id: str, document_ids: Sequence[UUID]
    ) -> dict[UUID, DocumentInfo]:
        return {
            document_id: DocumentInfo(name, content_type, *self.web_sources.get(document_id, ()))
            for document_id, (owner, name, content_type, _when) in self.documents.items()
            if owner == owner_id and document_id in document_ids
        }


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


class InMemoryConversationRepository:
    """Owner-scoped like the real one."""

    def __init__(self) -> None:
        self.conversations: dict[UUID, Conversation] = {}
        self.stored: list[tuple[str, StoredMessage]] = []  # (owner, message)
        self.usage: list[tuple[str, UsageEvent]] = []

    async def create(self, owner_id: str, title: str) -> Conversation:
        now = datetime.now(UTC)
        conversation = Conversation(uuid.uuid4(), owner_id, title, now, now)
        self.conversations[conversation.id] = conversation
        return conversation

    async def get(self, owner_id: str, conversation_id: UUID) -> Conversation | None:
        found = self.conversations.get(conversation_id)
        return found if found is not None and found.owner_id == owner_id else None

    async def list_by_owner(
        self, owner_id: str, *, limit: int = 50, offset: int = 0
    ) -> list[Conversation]:
        mine = [c for c in self.conversations.values() if c.owner_id == owner_id]
        mine.sort(key=lambda c: c.updated_at, reverse=True)
        return mine[offset : offset + limit]

    async def delete(self, owner_id: str, conversation_id: UUID) -> bool:
        if await self.get(owner_id, conversation_id) is None:
            return False
        del self.conversations[conversation_id]
        self.stored = [(o, m) for o, m in self.stored if m.conversation_id != conversation_id]
        return True

    async def add_message(
        self,
        owner_id: str,
        conversation_id: UUID,
        *,
        role: str,
        content: str,
        citations: tuple[Citation, ...] = (),
        refused: bool = False,
        refusal_reason: str | None = None,
    ) -> StoredMessage:
        assert role in ("user", "assistant")
        kind: Literal["user", "assistant"] = "user" if role == "user" else "assistant"
        message = StoredMessage(
            id=uuid.uuid4(),
            conversation_id=conversation_id,
            role=kind,
            content=content,
            citations=citations,
            refused=refused,
            refusal_reason=refusal_reason,
            created_at=datetime.now(UTC),
        )
        self.stored.append((owner_id, message))
        return message

    async def messages(
        self, owner_id: str, conversation_id: UUID, *, limit: int = 200
    ) -> list[StoredMessage]:
        mine = [m for o, m in self.stored if o == owner_id and m.conversation_id == conversation_id]
        return mine[-limit:] if limit else []

    async def record_usage(self, owner_id: str, event: UsageEvent) -> None:
        self.usage.append((owner_id, event))


class ScriptedChatModel:
    """A chat model that replies from a script and records what it was sent.

    ``stream_replies`` and ``complete_replies`` are consumed in order; the last one repeats.
    ``stream_closed`` turns true when the stream generator is closed, however that happens.
    """

    model_name = "scripted"

    def __init__(
        self,
        stream_replies: Sequence[str] = (),
        complete_replies: Sequence[str] = (),
        *,
        complete_error: EkaError | None = None,
        stream_error: EkaError | None = None,
    ) -> None:
        self._stream_replies = list(stream_replies)
        self._complete_replies = list(complete_replies)
        self._complete_error = complete_error
        self._stream_error = stream_error
        self.stream_calls: list[list[ChatMessage]] = []
        self.complete_calls: list[list[ChatMessage]] = []
        self.stream_closed = False

    @staticmethod
    def _next(replies: list[str]) -> str:
        return replies.pop(0) if len(replies) > 1 else (replies[0] if replies else "")

    async def complete(
        self, messages: Sequence[ChatMessage], *, max_tokens: int, usage: TokenUsage | None = None
    ) -> str:
        self.complete_calls.append(list(messages))
        if self._complete_error is not None:
            raise self._complete_error
        reply = self._next(self._complete_replies)
        if usage is not None:  # 100 prompt tokens and one per word, as a provider would report
            usage.add(self.model_name, "scripted", 100, len(reply.split()))
        return reply

    async def stream(
        self, messages: Sequence[ChatMessage], *, max_tokens: int, usage: TokenUsage | None = None
    ) -> AsyncGenerator[str, None]:
        self.stream_calls.append(list(messages))
        try:
            if self._stream_error is not None:
                raise self._stream_error
            reply = self._next(self._stream_replies)
            if usage is not None:
                usage.add(self.model_name, "scripted", 100, len(reply.split()))
            for word in reply.split(" "):
                await asyncio.sleep(0)
                yield word + " "
        finally:
            self.stream_closed = True
