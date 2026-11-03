"""Repository implementations. Each method filters by ``owner_id`` explicitly (layer one of
ADR-012); the session's row-level security is layer two."""

from uuid import UUID

from sqlalchemy import RowMapping, delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from eka.adapters.db.tables import documents
from eka.domain.models import Document, DocumentStatus, NewDocument


def _to_document(row: RowMapping) -> Document:
    return Document(
        id=row["id"],
        owner_id=row["owner_id"],
        filename=row["filename"],
        content_type=row["content_type"],
        size_bytes=row["size_bytes"],
        sha256=row["sha256"],
        storage_key=row["storage_key"],
        status=DocumentStatus(row["status"]),
        error_code=row["error_code"],
        attempts=row["attempts"],
        page_count=row["page_count"],
        chunk_count=row["chunk_count"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class SqlDocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, owner_id: str, new: NewDocument) -> tuple[Document, bool]:
        inserted = await self._session.execute(
            insert(documents)
            .values(
                id=new.id,
                owner_id=owner_id,
                filename=new.filename,
                content_type=new.content_type,
                size_bytes=new.size_bytes,
                sha256=new.sha256,
                storage_key=new.storage_key,
            )
            .on_conflict_do_nothing(constraint="documents_owner_sha256_key")
            .returning(documents)
        )
        row = inserted.mappings().first()
        if row is not None:
            return _to_document(row), True
        # Identical bytes already uploaded by this owner: hand back the existing document.
        existing = await self._session.execute(
            select(documents).where(
                documents.c.owner_id == owner_id, documents.c.sha256 == new.sha256
            )
        )
        return _to_document(existing.mappings().one()), False

    async def get(self, owner_id: str, document_id: UUID) -> Document | None:
        result = await self._session.execute(
            select(documents).where(documents.c.owner_id == owner_id, documents.c.id == document_id)
        )
        row = result.mappings().first()
        return _to_document(row) if row is not None else None

    async def list_by_owner(
        self,
        owner_id: str,
        *,
        status: DocumentStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Document]:
        query = select(documents).where(documents.c.owner_id == owner_id)
        if status is not None:
            query = query.where(documents.c.status == status.value)
        query = query.order_by(documents.c.created_at.desc(), documents.c.id).limit(limit)
        result = await self._session.execute(query.offset(offset))
        return [_to_document(row) for row in result.mappings()]

    async def get_by_sha256(self, owner_id: str, sha256: str) -> Document | None:
        result = await self._session.execute(
            select(documents).where(documents.c.owner_id == owner_id, documents.c.sha256 == sha256)
        )
        row = result.mappings().first()
        return _to_document(row) if row is not None else None

    async def count_by_owner(self, owner_id: str) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(documents).where(documents.c.owner_id == owner_id)
        )
        return int(result.scalar_one())

    async def delete(self, owner_id: str, document_id: UUID) -> bool:
        result = await self._session.execute(
            delete(documents)
            .where(documents.c.owner_id == owner_id, documents.c.id == document_id)
            .returning(documents.c.id)
        )
        return result.first() is not None
