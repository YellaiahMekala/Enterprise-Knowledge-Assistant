import time
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
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
