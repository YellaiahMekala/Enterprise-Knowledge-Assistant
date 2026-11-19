# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""Response models shared by routers. They exist mainly to document the contract in OpenAPI."""

from datetime import datetime
from typing import Any, Self
from uuid import UUID

from pydantic import BaseModel

from eka.domain.models import Document, DocumentStatus, Role

PROBLEM_MEDIA_TYPE = "application/problem+json"


class Me(BaseModel):
    user_id: str
    role: Role


class DocumentOut(BaseModel):
    """A document and where it is in ingestion (TDD 6.2). ``error_code`` is a fixed code such as
    ``encrypted``, ``no_text``, ``corrupt``, ``too_large``, ``unsupported_encoding`` or
    ``max_attempts``."""

    id: UUID
    filename: str
    content_type: str
    size_bytes: int
    status: DocumentStatus
    error_code: str | None
    page_count: int | None
    chunk_count: int | None
    created_at: datetime
    updated_at: datetime
    source_url: str | None = None
    fetched_at: datetime | None = None

    @classmethod
    def from_domain(cls, document: Document) -> Self:
        return cls(
            id=document.id,
            filename=document.filename,
            content_type=document.content_type,
            size_bytes=document.size_bytes,
            status=document.status,
            error_code=document.error_code,
            page_count=document.page_count,
            chunk_count=document.chunk_count,
            created_at=document.created_at,
            updated_at=document.updated_at,
            source_url=document.source_url,
            fetched_at=document.fetched_at,
        )


class DocumentList(BaseModel):
    items: list[DocumentOut]
    limit: int
    offset: int


class Problem(BaseModel):
    """RFC 9457 problem details; see TDD 6.4."""

    type: str
    title: str
    status: int
    detail: str
    instance: str
    request_id: str


UNAUTHORIZED_RESPONSE: dict[int | str, dict[str, Any]] = {
    401: {"model": Problem, "description": "Missing or invalid API key."}
}
NOT_FOUND_RESPONSE: dict[int | str, dict[str, Any]] = {
    404: {"model": Problem, "description": "No such document (or it belongs to another user)."}
}
