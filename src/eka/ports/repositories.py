"""Repository ports.

Isolation rule (ADR-012): every method takes ``owner_id`` as its first argument, so a query
without an owner does not type-check. ``tests/test_architecture.py`` asserts this signature.
"""

from typing import Protocol
from uuid import UUID

from eka.domain.models import (
    Citation,
    Conversation,
    Document,
    DocumentStatus,
    NewDocument,
    StoredMessage,
    UsageEvent,
)


class DocumentRepository(Protocol):
    async def add(self, owner_id: str, new: NewDocument) -> tuple[Document, bool]:
        """Insert a document. Returns ``(document, created)``; when the owner already has a
        document with the same SHA-256 the existing one is returned with ``created=False``."""
        ...

    async def get(self, owner_id: str, document_id: UUID) -> Document | None:
        """The owner's document, or ``None`` (also for another user's id)."""
        ...

    async def list_by_owner(
        self,
        owner_id: str,
        *,
        status: DocumentStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Document]:
        """The owner's documents, newest first."""
        ...

    async def get_by_sha256(self, owner_id: str, sha256: str) -> Document | None:
        """The owner's document with these exact bytes, or ``None``."""
        ...

    async def web_copies(self, owner_id: str, source_url: str) -> list[Document]:
        """The owner's stored copies of a web page, newest fetch first."""
        ...

    async def count_by_owner(self, owner_id: str) -> int:
        """How many documents the owner holds (for the quota)."""
        ...

    async def delete(self, owner_id: str, document_id: UUID) -> bool:
        """Delete the document and, by cascade, its chunks. ``False`` if there was none."""
        ...


class ConversationRepository(Protocol):
    async def create(self, owner_id: str, title: str) -> Conversation: ...

    async def get(self, owner_id: str, conversation_id: UUID) -> Conversation | None:
        """The owner's conversation, or ``None`` (also for another user's id)."""
        ...

    async def list_by_owner(
        self, owner_id: str, *, limit: int = 50, offset: int = 0
    ) -> list[Conversation]:
        """The owner's conversations, most recently active first."""
        ...

    async def delete(self, owner_id: str, conversation_id: UUID) -> bool:
        """Delete the conversation and, by cascade, its messages. ``False`` if there was none."""
        ...

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
        """Append a message and mark the conversation as active now."""
        ...

    async def messages(
        self, owner_id: str, conversation_id: UUID, *, limit: int = 200
    ) -> list[StoredMessage]:
        """The most recent ``limit`` messages, oldest first."""
        ...

    async def record_usage(self, owner_id: str, event: UsageEvent) -> None: ...
