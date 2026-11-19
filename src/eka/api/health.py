# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""Liveness and readiness probes for Docker, Kubernetes and load balancers."""

import asyncio
import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from eka import __version__
from eka.api.deps import ReadinessCheck, get_readiness_check
from eka.api.schemas import Problem
from eka.domain.errors import Unavailable

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"])

# A probe must answer quickly; a hung database should read as "not ready", not hang the probe.
READINESS_TIMEOUT_S = 2.0


class Liveness(BaseModel):
    status: Literal["ok"] = "ok"


class Readiness(BaseModel):
    status: Literal["ok"] = "ok"
    version: str


@router.get("/live")
def live() -> Liveness:
    """The process is up and serving requests."""
    return Liveness()


@router.get(
    "/ready",
    responses={503: {"model": Problem, "description": "A dependency is unavailable."}},
)
async def ready(check: Annotated[ReadinessCheck, Depends(get_readiness_check)]) -> Readiness:
    """Ready for traffic: the database answers. Returns the build version."""
    try:
        await asyncio.wait_for(check(), timeout=READINESS_TIMEOUT_S)
    except Exception as error:
        # One line per failed probe (probes are frequent). The detail (driver message, host)
        # stays in the log; the probe only sees 503.
        logger.warning("readiness check failed: %s: %s", type(error).__name__, error)
        raise Unavailable from None
    return Readiness(version=__version__)
