"""PostgreSQL implementation of the worker queue (TDD 4.9, ADR-010).

The queue is the ``documents`` table itself: ``status`` is the state machine, ``FOR UPDATE SKIP
LOCKED`` lets several workers claim without blocking each other, and a claim older than the stale
limit is taken over, so a crashed worker's document is not stuck forever.
"""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete, insert, text

from eka.adapters.db.engine import Database
from eka.adapters.db.tables import chunks
from eka.domain.errors import MAX_ATTEMPTS
from eka.domain.models import ClaimedDocument, NewChunk

_INSERT_BATCH = 100

_FAIL_EXHAUSTED = text(
    """
    UPDATE documents
       SET status = 'failed', error_code = :code, locked_at = NULL, updated_at = now()
     WHERE status = 'processing'
       AND locked_at < now() - make_interval(mins => :stale)
       AND attempts >= :max_attempts
    """
)

_CLAIM = text(
    """
    UPDATE documents
       SET status = 'processing', locked_at = now(), attempts = attempts + 1, updated_at = now()
     WHERE id = (
            SELECT id FROM documents
             WHERE status = 'pending'
                OR (status = 'processing' AND locked_at < now() - make_interval(mins => :stale))
             ORDER BY created_at
               FOR UPDATE SKIP LOCKED
             LIMIT 1)
    RETURNING id, owner_id, filename, content_type, storage_key, attempts
    """
)

_COMPLETE = text(
    """
    UPDATE documents
       SET status = 'ready', error_code = NULL, page_count = :page_count,
           chunk_count = :chunk_count, locked_at = NULL, updated_at = now()
     WHERE id = :id AND status = 'processing'
    RETURNING owner_id
    """
)

_FAIL = text(
    """
    UPDATE documents
       SET status = 'failed', error_code = :code, locked_at = NULL, updated_at = now()
     WHERE id = :id AND status = 'processing'
    """
)

_RELEASE = text(
    """
    UPDATE documents
       SET status     = CASE WHEN attempts >= :max_attempts THEN 'failed' ELSE 'pending' END,
           error_code = CASE WHEN attempts >= :max_attempts THEN :code END,
           locked_at  = NULL, updated_at = now()
     WHERE id = :id AND status = 'processing'
    """
)


class SqlIngestionQueue:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def claim(self, *, stale_minutes: int, max_attempts: int) -> ClaimedDocument | None:
        async with self._database.worker_session() as session:
            await session.execute(
                _FAIL_EXHAUSTED,
                {"code": MAX_ATTEMPTS, "stale": stale_minutes, "max_attempts": max_attempts},
            )
            result = await session.execute(_CLAIM, {"stale": stale_minutes})
            row = result.mappings().first()
        if row is None:
            return None
        return ClaimedDocument(
            id=row["id"],
            owner_id=row["owner_id"],
            filename=row["filename"],
            content_type=row["content_type"],
            storage_key=row["storage_key"],
            attempts=row["attempts"],
        )

    async def complete(
        self,
        document_id: UUID,
        new_chunks: Sequence[NewChunk],
        *,
        page_count: int | None,
        embedding_model: str,
        chunk_config: str,
    ) -> bool:
        async with self._database.worker_session() as session:
            # The UPDATE comes first: it locks the row, so a concurrent delete waits for us, and
            # if the document is already gone nothing below runs.
            updated = await session.execute(
                _COMPLETE,
                {"id": document_id, "page_count": page_count, "chunk_count": len(new_chunks)},
            )
            owner = updated.scalar_one_or_none()
            if owner is None:
                return False
            await session.execute(delete(chunks).where(chunks.c.document_id == document_id))
            rows = [
                {
                    "document_id": document_id,
                    "owner_id": owner,
                    "ordinal": item.chunk.ordinal,
                    "text": item.chunk.text,
                    "locator": dict(item.chunk.locator),
                    "char_start": item.chunk.char_start,
                    "char_end": item.chunk.char_end,
                    "token_count": item.chunk.token_count,
                    "embedding": list(item.embedding),
                    "embedding_model": embedding_model,
                    "chunk_config": chunk_config,
                }
                for item in new_chunks
            ]
            for start in range(0, len(rows), _INSERT_BATCH):
                await session.execute(insert(chunks), rows[start : start + _INSERT_BATCH])
            return True

    async def fail(self, document_id: UUID, error_code: str) -> None:
        async with self._database.worker_session() as session:
            await session.execute(_FAIL, {"id": document_id, "code": error_code})

    async def release(self, document_id: UUID, *, max_attempts: int) -> None:
        async with self._database.worker_session() as session:
            await session.execute(
                _RELEASE, {"id": document_id, "max_attempts": max_attempts, "code": MAX_ATTEMPTS}
            )
