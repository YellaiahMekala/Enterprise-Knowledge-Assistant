"""Repository implementations. Each method filters by ``owner_id`` explicitly (layer one of
ADR-012); the session's row-level security is layer two."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import RowMapping, delete, func, select, update
from sqlalchemy import insert as core_insert
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from eka.adapters.db.tables import conversations, documents, messages, usage_events
from eka.domain.models import (
    Citation,
    Conversation,
    Document,
    DocumentStatus,
    NewDocument,
    StoredMessage,
    UsageEvent,
    UsageRow,
)


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
        source_url=row["source_url"],
        fetched_at=row["fetched_at"],
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
                source_url=new.source_url,
                fetched_at=new.fetched_at,
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

    async def web_copies(self, owner_id: str, source_url: str) -> list[Document]:
        result = await self._session.execute(
            select(documents)
            .where(documents.c.owner_id == owner_id, documents.c.source_url == source_url)
            .order_by(documents.c.fetched_at.desc())
        )
        return [_to_document(row) for row in result.mappings()]

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


def citation_to_json(citation: Citation) -> dict[str, Any]:
    return {
        "index": citation.index,
        "chunk_id": str(citation.chunk_id),
        "document_id": str(citation.document_id),
        "filename": citation.filename,
        "locator": dict(citation.locator),
        "quote": citation.quote,
        "source_url": citation.source_url,
        "fetched_at": citation.fetched_at.isoformat() if citation.fetched_at else None,
    }


def citation_from_json(data: dict[str, Any]) -> Citation:
    return Citation(
        index=int(data["index"]),
        chunk_id=UUID(data["chunk_id"]),
        document_id=UUID(data["document_id"]),
        filename=data["filename"],
        locator=data["locator"],
        quote=data["quote"],
        source_url=data.get("source_url"),
        fetched_at=datetime.fromisoformat(data["fetched_at"]) if data.get("fetched_at") else None,
    )


def _to_conversation(row: RowMapping) -> Conversation:
    return Conversation(
        id=row["id"],
        owner_id=row["owner_id"],
        title=row["title"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _to_message(row: RowMapping) -> StoredMessage:
    return StoredMessage(
        id=row["id"],
        conversation_id=row["conversation_id"],
        role=row["role"],
        content=row["content"],
        citations=tuple(citation_from_json(c) for c in row["citations"]),
        refused=row["refused"],
        refusal_reason=row["refusal_reason"],
        created_at=row["created_at"],
    )


class SqlConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, owner_id: str, title: str) -> Conversation:
        result = await self._session.execute(
            core_insert(conversations)
            .values(owner_id=owner_id, title=title)
            .returning(conversations)
        )
        return _to_conversation(result.mappings().one())

    async def get(self, owner_id: str, conversation_id: UUID) -> Conversation | None:
        result = await self._session.execute(
            select(conversations).where(
                conversations.c.owner_id == owner_id, conversations.c.id == conversation_id
            )
        )
        row = result.mappings().first()
        return _to_conversation(row) if row is not None else None

    async def list_by_owner(
        self, owner_id: str, *, limit: int = 50, offset: int = 0
    ) -> list[Conversation]:
        result = await self._session.execute(
            select(conversations)
            .where(conversations.c.owner_id == owner_id)
            .order_by(conversations.c.updated_at.desc(), conversations.c.id)
            .limit(limit)
            .offset(offset)
        )
        return [_to_conversation(row) for row in result.mappings()]

    async def delete(self, owner_id: str, conversation_id: UUID) -> bool:
        result = await self._session.execute(
            delete(conversations)
            .where(conversations.c.owner_id == owner_id, conversations.c.id == conversation_id)
            .returning(conversations.c.id)
        )
        return result.first() is not None

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
        result = await self._session.execute(
            core_insert(messages)
            .values(
                conversation_id=conversation_id,
                owner_id=owner_id,
                role=role,
                content=content,
                citations=[citation_to_json(c) for c in citations],
                refused=refused,
                refusal_reason=refusal_reason,
            )
            .returning(messages)
        )
        await self._session.execute(
            update(conversations)
            .where(conversations.c.owner_id == owner_id, conversations.c.id == conversation_id)
            .values(updated_at=func.now())
        )
        return _to_message(result.mappings().one())

    async def messages(
        self, owner_id: str, conversation_id: UUID, *, limit: int = 200
    ) -> list[StoredMessage]:
        newest = (
            select(messages)
            .where(messages.c.owner_id == owner_id, messages.c.conversation_id == conversation_id)
            .order_by(messages.c.seq.desc())
            .limit(limit)
            .subquery()
        )
        result = await self._session.execute(select(newest).order_by(newest.c.seq))
        return [_to_message(row) for row in result.mappings()]

    async def record_usage(self, owner_id: str, event: UsageEvent) -> None:
        await self._session.execute(
            core_insert(usage_events).values(
                owner_id=owner_id,
                conversation_id=event.conversation_id,
                mode=event.mode,
                model=event.model,
                refused=event.refused,
                retrieved=event.retrieved,
                top_cosine=event.top_cosine,
                prompt_chars=event.prompt_chars,
                completion_chars=event.completion_chars,
                latency_ms=event.latency_ms,
                provider=event.provider,
                prompt_tokens=event.prompt_tokens,
                completion_tokens=event.completion_tokens,
                token_source=event.token_source,
                cost_usd=event.cost_usd,
                ttft_ms=event.ttft_ms,
                answer_ttfb_ms=event.answer_ttfb_ms,
            )
        )


class SqlUsageReport:
    """Usage summed by user or by day. Needs a session opened with the admin role, whose
    row-level policy may read every owner's usage events."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def summary(self, group_by: str, start: datetime, end: datetime) -> list[UsageRow]:
        if group_by == "user":
            key: Any = usage_events.c.owner_id
        else:
            key = func.to_char(
                func.date_trunc("day", func.timezone("UTC", usage_events.c.created_at)),
                "YYYY-MM-DD",
            )
        u = usage_events.c

        def pct(fraction: float, column: Any) -> Any:
            return func.percentile_cont(fraction).within_group(column)

        query = (
            select(
                key.label("key"),
                func.count().label("requests"),
                func.count().filter(u.refused).label("refused"),
                func.sum(u.prompt_tokens).label("prompt_tokens"),
                func.sum(u.completion_tokens).label("completion_tokens"),
                func.sum(u.cost_usd).label("cost_usd"),
                pct(0.5, u.latency_ms).label("latency_p50"),
                pct(0.95, u.latency_ms).label("latency_p95"),
                pct(0.5, u.ttft_ms).label("ttft_p50"),
                pct(0.95, u.ttft_ms).label("ttft_p95"),
            )
            .where(u.created_at >= start, u.created_at < end)
            .group_by(key)
            .order_by(key)
        )
        rows = (await self._session.execute(query)).mappings()
        return [
            UsageRow(
                key=str(row["key"]),
                requests=int(row["requests"]),
                refused=int(row["refused"]),
                prompt_tokens=_int_or_none(row["prompt_tokens"]),
                completion_tokens=_int_or_none(row["completion_tokens"]),
                cost_usd=float(row["cost_usd"]) if row["cost_usd"] is not None else None,
                latency_p50_ms=_int_or_none(row["latency_p50"]),
                latency_p95_ms=_int_or_none(row["latency_p95"]),
                ttft_p50_ms=_int_or_none(row["ttft_p50"]),
                ttft_p95_ms=_int_or_none(row["ttft_p95"]),
            )
            for row in rows
        ]


async def document_status_counts(session: AsyncSession) -> dict[str, int]:
    """Documents of every owner by status; needs a session opened with the admin role."""
    rows = await session.execute(
        select(documents.c.status, func.count()).group_by(documents.c.status)
    )
    return {str(status): int(count) for status, count in rows.all()}


def _int_or_none(value: Any) -> int | None:
    return None if value is None else round(float(value))
