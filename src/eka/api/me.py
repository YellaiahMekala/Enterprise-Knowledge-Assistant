"""Who am I: the caller's id and role, taken from the credential."""

from fastapi import APIRouter

from eka.api.deps import CurrentPrincipal
from eka.api.schemas import UNAUTHORIZED_RESPONSE, Me

router = APIRouter(prefix="/api/v1", tags=["identity"])


@router.get("/me", responses=UNAUTHORIZED_RESPONSE)
async def me(principal: CurrentPrincipal) -> Me:
    """The authenticated caller (in edge mode, phase P3b, the edge answers from token claims)."""
    return Me(user_id=principal.user_id, role=principal.role)
