# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""The worker's view of the ingestion queue (TDD 4.9, ADR-010).

This is deliberately **not** a ``*Repository``: it works across owners (the worker serves every
user), so its methods do not take ``owner_id`` first. That is safe because it runs only in the
worker process, as the ``eka_worker`` database role, whose grants are limited to the two tables
and whose policies are explicit (see migration 0001). The API never uses it.
"""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from eka.domain.models import ClaimedDocument, NewChunk


class IngestionQueue(Protocol):
    async def claim(self, *, stale_minutes: int, max_attempts: int) -> ClaimedDocument | None:
        """Take the oldest pending document (or one whose claim went stale), or ``None``.
        Several workers can call this at once; each document goes to exactly one of them."""
        ...

    async def complete(
        self,
        document_id: UUID,
        chunks: Sequence[NewChunk],
        *,
        page_count: int | None,
        embedding_model: str,
        chunk_config: str,
    ) -> bool:
        """In one transaction: replace the document's chunks and mark it ``ready``.
        Returns ``False`` (and stores nothing) if the document was deleted meanwhile."""
        ...

    async def fail(self, document_id: UUID, error_code: str) -> None:
        """Permanent failure: mark ``failed`` with a fixed error code; no retry."""
        ...

    async def release(self, document_id: UUID, *, max_attempts: int) -> None:
        """Transient failure: back to ``pending``, or ``failed`` with ``max_attempts`` once the
        attempt budget is used up."""
        ...
