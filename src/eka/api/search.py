"""POST /api/v1/search: ranked passages for a question, scoped to the caller (TDD 6.1)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field

from eka.api.deps import CurrentPrincipal, EmbedderFor, RetrievalServices
from eka.api.schemas import UNAUTHORIZED_RESPONSE
from eka.domain.models import SearchFilters, SearchHit
from eka.services.retrieval import MAX_QUERY_CHARS

router = APIRouter(prefix="/api/v1", tags=["search"])


class SearchFiltersIn(BaseModel):
    document_ids: list[UUID] = Field(default_factory=list, max_length=200)
    content_types: list[str] = Field(default_factory=list, max_length=10)
    uploaded_after: datetime | None = None
    uploaded_before: datetime | None = None


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)
    top_k: int = Field(default=5, ge=1, le=20)
    filters: SearchFiltersIn = Field(default_factory=SearchFiltersIn)


class ScoresOut(BaseModel):
    fused: float
    cosine: float
    rerank: float | None = None  # set once reranking exists


class SearchResultOut(BaseModel):
    rank: int
    chunk_id: UUID
    document_id: UUID
    filename: str
    locator: dict[str, Any]
    text: str
    scores: ScoresOut

    @classmethod
    def from_hit(cls, hit: SearchHit) -> "SearchResultOut":
        return cls(
            rank=hit.rank,
            chunk_id=hit.chunk_id,
            document_id=hit.document_id,
            filename=hit.filename,
            locator=dict(hit.locator),
            text=hit.text,
            scores=ScoresOut(fused=hit.fused, cosine=hit.cosine),
        )


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResultOut]


@router.post("/search", responses=UNAUTHORIZED_RESPONSE)
async def search(
    body: SearchRequest,
    principal: CurrentPrincipal,
    services: RetrievalServices,
    embedder_for: EmbedderFor,
) -> SearchResponse:
    """Ranked passages, best first. Filters narrow the caller's own documents only."""
    embedder = await embedder_for()
    filters = SearchFilters(
        document_ids=tuple(body.filters.document_ids),
        content_types=tuple(body.filters.content_types),
        uploaded_after=body.filters.uploaded_after,
        uploaded_before=body.filters.uploaded_before,
    )
    async with services(principal.user_id, principal.role, embedder) as service:
        hits = await service.search(
            principal.user_id, body.query, top_k=body.top_k, filters=filters
        )
    return SearchResponse(query=body.query, results=[SearchResultOut.from_hit(h) for h in hits])
