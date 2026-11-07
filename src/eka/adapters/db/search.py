"""PostgreSQL implementation of the retrieval port (TDD 4.6).

Dense search has two paths, chosen by the service from the owner's chunk count: exact (index scan
off, sorted by distance) and approximate (HNSW with iterative scan). All settings are
transaction-local. Every query repeats the owner predicate; row-level security is the second layer.
"""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from eka.domain.models import Candidate, SearchFilters

_VECTOR = "CAST(:vector AS vector)"


def _vector_literal(vector: Sequence[float]) -> str:
    return "[" + ",".join(repr(float(value)) for value in vector) + "]"


def _document_clause(
    document_ids: list[UUID] | None, column: str = "document_id"
) -> tuple[str, dict[str, Any]]:
    if document_ids is None:
        return "", {}
    clause = f" AND {column} = ANY(CAST(:document_ids AS uuid[]))"
    return clause, {"document_ids": document_ids}


class SqlChunkSearch:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def count_chunks(self, owner_id: str) -> int:
        result = await self._session.execute(
            text("SELECT count(*) FROM chunks WHERE owner_id = :owner"), {"owner": owner_id}
        )
        return int(result.scalar_one())

    async def resolve_documents(self, owner_id: str, filters: SearchFilters) -> list[UUID] | None:
        if filters.is_empty:
            return None
        clauses = ["owner_id = :owner"]
        params: dict[str, Any] = {"owner": owner_id}
        if filters.document_ids:
            clauses.append("id = ANY(CAST(:ids AS uuid[]))")
            params["ids"] = list(filters.document_ids)
        if filters.content_types:
            clauses.append("content_type = ANY(CAST(:types AS text[]))")
            params["types"] = list(filters.content_types)
        if filters.uploaded_after is not None:
            clauses.append("created_at >= :after")
            params["after"] = filters.uploaded_after
        if filters.uploaded_before is not None:
            clauses.append("created_at < :before")
            params["before"] = filters.uploaded_before
        result = await self._session.execute(
            text("SELECT id FROM documents WHERE " + " AND ".join(clauses)), params
        )
        return [row.id for row in result]

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
        await self.configure_scan(exact=exact, ef_search=ef_search)
        clause, params = _document_clause(document_ids)
        result = await self._session.execute(
            text(
                f"""
                SELECT id, document_id, text, locator,
                       embedding <=> {_VECTOR} AS distance
                FROM chunks
                WHERE owner_id = :owner{clause}
                ORDER BY embedding <=> {_VECTOR}
                LIMIT :limit
                """
            ),
            {"owner": owner_id, "vector": _vector_literal(vector), "limit": limit, **params},
        )
        rows = list(result)
        # The sparse query in the same transaction needs bitmap scans again.
        await self._session.execute(
            text(
                "SELECT set_config('enable_bitmapscan', 'on', true), "
                "set_config('enable_seqscan', 'on', true)"
            )
        )
        return [
            Candidate(row.id, row.document_id, row.text, row.locator, float(row.distance))
            for row in rows
        ]

    async def configure_scan(self, *, exact: bool, ef_search: int) -> None:
        """Set the planner switches for the dense query, for this transaction only.

        The approximate path turns off bitmap and sequential scans so the HNSW index is the
        access method; the exact path turns off index scans so rows are sorted by distance."""
        await self._session.execute(
            text(
                "SELECT set_config('enable_indexscan', :indexscan, true), "
                "set_config('enable_bitmapscan', :plain, true), "
                "set_config('enable_seqscan', :plain, true), "
                "set_config('hnsw.iterative_scan', :iterative, true), "
                "set_config('hnsw.ef_search', :ef, true)"
            ),
            {
                "indexscan": "off" if exact else "on",
                "plain": "on" if exact else "off",
                "iterative": "off" if exact else "relaxed_order",
                "ef": str(ef_search),
            },
        )

    async def sparse(
        self,
        owner_id: str,
        query: str,
        limit: int,
        *,
        document_ids: list[UUID] | None,
    ) -> list[Candidate]:
        clause, params = _document_clause(document_ids, "c.document_id")
        result = await self._session.execute(
            text(
                f"""
                WITH q AS (SELECT to_tsquery('english', :query) AS query)
                SELECT c.id, c.document_id, c.text, c.locator,
                       ts_rank_cd(c.tsv, q.query) AS score
                FROM chunks AS c, q
                WHERE c.owner_id = :owner AND c.tsv @@ q.query{clause}
                ORDER BY score DESC
                LIMIT :limit
                """
            ),
            {"owner": owner_id, "query": query, "limit": limit, **params},
        )
        return [
            Candidate(row.id, row.document_id, row.text, row.locator, float(row.score))
            for row in result
        ]

    async def cosine(
        self, owner_id: str, vector: Sequence[float], chunk_ids: Sequence[UUID]
    ) -> dict[UUID, float]:
        if not chunk_ids:
            return {}
        result = await self._session.execute(
            text(
                f"""
                SELECT id, 1 - (embedding <=> {_VECTOR}) AS similarity
                FROM chunks
                WHERE owner_id = :owner AND id = ANY(CAST(:ids AS uuid[]))
                """
            ),
            {"owner": owner_id, "vector": _vector_literal(vector), "ids": list(chunk_ids)},
        )
        return {row.id: float(row.similarity) for row in result}

    async def document_info(
        self, owner_id: str, document_ids: Sequence[UUID]
    ) -> dict[UUID, tuple[str, str]]:
        if not document_ids:
            return {}
        result = await self._session.execute(
            text(
                "SELECT id, filename, content_type FROM documents "
                "WHERE owner_id = :owner AND id = ANY(CAST(:ids AS uuid[]))"
            ),
            {"owner": owner_id, "ids": list(document_ids)},
        )
        return {row.id: (row.filename, row.content_type) for row in result}
