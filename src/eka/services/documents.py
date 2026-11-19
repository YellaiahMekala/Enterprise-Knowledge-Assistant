# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""Document use cases for the API: upload, read, list, delete (TDD 4.2, 6.1).

The service holds no database session of its own: it is handed a repository that is already
scoped to one user (row-level security, ADR-012), plus a file store.
"""

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from eka.domain.errors import NotFound, PayloadTooLarge, QuotaExceeded
from eka.domain.models import Document, DocumentStatus, NewDocument
from eka.ingestion.sniff import clean_filename, sniff
from eka.ports.repositories import DocumentRepository
from eka.ports.storage import FileStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class UploadPolicy:
    max_upload_bytes: int
    max_documents: int
    text_extensions: tuple[str, ...]
    max_text_bytes: int


class DocumentService:
    def __init__(
        self, repository: DocumentRepository, store: FileStore, policy: UploadPolicy
    ) -> None:
        self._repository = repository
        self._store = store
        self._policy = policy

    async def upload(
        self,
        owner_id: str,
        filename: str | None,
        declared_content_type: str | None,
        data: bytes,
        *,
        source_url: str | None = None,
        fetched_at: datetime | None = None,
    ) -> tuple[Document, bool]:
        """Validate, store and queue a file. Returns ``(document, created)``; uploading the same
        bytes again returns the existing document with ``created=False`` and stores nothing."""
        if len(data) > self._policy.max_upload_bytes:
            raise PayloadTooLarge()
        name = clean_filename(filename)
        sniffed = sniff(
            name,
            declared_content_type,
            data,
            text_extensions=self._policy.text_extensions,
            max_text_bytes=self._policy.max_text_bytes,
        )
        digest = hashlib.sha256(data).hexdigest()

        existing = await self._repository.get_by_sha256(owner_id, digest)
        if existing is not None:
            return existing, False
        if await self._repository.count_by_owner(owner_id) >= self._policy.max_documents:
            raise QuotaExceeded()

        document_id = uuid.uuid4()
        key = f"{owner_id}/{document_id}"
        await self._store.put(key, data, sniffed.content_type)
        try:
            document, created = await self._repository.add(
                owner_id,
                NewDocument(
                    id=document_id,
                    filename=name,
                    content_type=sniffed.content_type,
                    size_bytes=len(data),
                    sha256=digest,
                    storage_key=key,
                    source_url=source_url,
                    fetched_at=fetched_at,
                ),
            )
        except BaseException:
            await self._discard(key)
            raise
        if not created:  # a concurrent identical upload won the race
            await self._discard(key)
        return document, created

    async def get(self, owner_id: str, document_id: UUID) -> Document:
        document = await self._repository.get(owner_id, document_id)
        if document is None:
            raise NotFound()
        return document

    async def web_copies(self, owner_id: str, source_url: str) -> list[Document]:
        return await self._repository.web_copies(owner_id, source_url)

    async def list(
        self,
        owner_id: str,
        *,
        status: DocumentStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Document]:
        return await self._repository.list_by_owner(
            owner_id, status=status, limit=limit, offset=offset
        )

    async def delete(self, owner_id: str, document_id: UUID) -> None:
        document = await self._repository.get(owner_id, document_id)
        if document is None or not await self._repository.delete(owner_id, document_id):
            raise NotFound()
        await self._discard(document.storage_key)

    async def _discard(self, key: str) -> None:
        """Remove a stored file; a failure leaves an orphan file, which must not fail the
        request that already did its database work."""
        try:
            await self._store.delete(key)
        except Exception:
            logger.warning("could not remove stored object %s", key, exc_info=True)
