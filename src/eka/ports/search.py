"""Retrieval port (TDD 4.6). Every method runs in one owner's session."""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from eka.domain.models import Candidate, SearchFilters


class ChunkSearch(Protocol):
    async def count_chunks(self, owner_id: str) -> int:
        """Number of chunks the owner has."""
        ...

    async def resolve_documents(self, owner_id: str, filters: SearchFilters) -> list[UUID] | None:
        """Ids of matching documents, or ``None`` when there are no filters."""
        ...

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
        """Nearest chunks by cosine distance: a sorted scan if ``exact``, else the HNSW index."""
        ...

    async def sparse(
        self,
        owner_id: str,
        query: str,
        limit: int,
        *,
        document_ids: list[UUID] | None,
    ) -> list[Candidate]:
        """Chunks matching the full-text query, ranked by ``ts_rank_cd``."""
        ...

    async def cosine(
        self, owner_id: str, vector: Sequence[float], chunk_ids: Sequence[UUID]
    ) -> dict[UUID, float]:
        """Exact cosine similarity for the given chunks."""
        ...

    async def document_info(
        self, owner_id: str, document_ids: Sequence[UUID]
    ) -> dict[UUID, tuple[str, str]]:
        """Map of document id to (filename, content type)."""
        ...
