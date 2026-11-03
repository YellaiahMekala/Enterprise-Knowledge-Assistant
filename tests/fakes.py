"""In-memory test doubles for the ports (Test Strategy section 4). They are deliberately simple
but honour each port's contract (owner scoping, idempotent delete), so service and API tests
exercise real behaviour without a database."""

import hashlib
import math
import re
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

from eka.domain.errors import Unavailable
from eka.domain.models import (
    ClaimedDocument,
    Document,
    DocumentStatus,
    NewChunk,
    NewDocument,
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
