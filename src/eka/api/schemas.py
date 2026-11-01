"""Response models shared by routers. They exist mainly to document the contract in OpenAPI."""

from typing import Any

from pydantic import BaseModel

from eka.domain.models import Role

PROBLEM_MEDIA_TYPE = "application/problem+json"


class Me(BaseModel):
    user_id: str
    role: Role


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
