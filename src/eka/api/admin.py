# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
import time
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel

from eka import __version__
from eka.api.deps import CurrentPrincipal
from eka.api.schemas import UNAUTHORIZED_RESPONSE
from eka.domain.errors import Forbidden
from eka.domain.models import Role
from eka.metrics import CONTENT_TYPE, Metrics
from eka.security.auth import Principal

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


async def require_admin(principal: CurrentPrincipal) -> Principal:
    if principal.role != Role.ADMIN:
        raise Forbidden()
    return principal


AdminOnly = Annotated[Principal, Depends(require_admin)]


class Status(BaseModel):
    version: str
    environment: str
    auth_mode: str | None
    uptime_seconds: int


@router.get("/status", responses=UNAUTHORIZED_RESPONSE)
async def status(request: Request, _: AdminOnly) -> Status:
    settings = request.app.state.settings
    return Status(
        version=__version__,
        environment=settings.environment,
        auth_mode=settings.auth_mode,
        uptime_seconds=int(time.monotonic() - request.app.state.started_at),
    )


@router.get(
    "/metrics",
    responses={200: {"content": {"text/plain": {}}}, **UNAUTHORIZED_RESPONSE},
    response_class=Response,
)
async def metrics(request: Request, _: AdminOnly) -> Response:
    metrics: Metrics = request.app.state.metrics
    return Response(metrics.render(), media_type=CONTENT_TYPE)


class UsageLine(BaseModel):
    """One user (pseudonymous id) or one UTC day. Counts and timings only, never text."""

    key: str
    requests: int
    refused: int
    prompt_tokens: int | None
    completion_tokens: int | None
    cost_usd: float | None
    latency_p50_ms: int | None
    latency_p95_ms: int | None
    ttft_p50_ms: int | None
    ttft_p95_ms: int | None


class UsageReport(BaseModel):
    group_by: Literal["user", "day"]
    start: datetime
    end: datetime
    rows: list[UsageLine]


_MAX_REPORT_DAYS = 92


@router.get("/usage", responses=UNAUTHORIZED_RESPONSE)
async def usage(
    request: Request,
    principal: AdminOnly,
    group_by: Annotated[Literal["user", "day"], Query()] = "day",
    start: Annotated[datetime | None, Query(alias="from")] = None,
    end: Annotated[datetime | None, Query(alias="to")] = None,
) -> UsageReport:
    """Requests, refusals, tokens, cost and p50/p95 latency and time to first token, by user or
    by day (ADR-037). The default window is the last 7 days; at most 92 days."""
    end = _aware(end) if end else datetime.now(UTC)
    start = _aware(start) if start else end - timedelta(days=7)
    if start >= end or end - start > timedelta(days=_MAX_REPORT_DAYS):
        raise HTTPException(
            400, f"'from' must be before 'to', at most {_MAX_REPORT_DAYS} days apart"
        )
    rows = await request.app.state.usage_report(principal.user_id, group_by, start, end)
    return UsageReport(
        group_by=group_by,
        start=start,
        end=end,
        rows=[UsageLine.model_validate(row, from_attributes=True) for row in rows],
    )


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


class DocumentCounts(BaseModel):
    """Documents of every user by status (pending, processing, ready, failed). No names."""

    total: int
    by_status: dict[str, int]


@router.get("/documents", responses=UNAUTHORIZED_RESPONSE)
async def document_counts(request: Request, principal: AdminOnly) -> DocumentCounts:
    counts: dict[str, int] = await request.app.state.document_counts(principal.user_id)
    statuses = ("pending", "processing", "ready", "failed")
    by_status = {status: counts.get(status, 0) for status in statuses}
    return DocumentCounts(total=sum(counts.values()), by_status=by_status)
