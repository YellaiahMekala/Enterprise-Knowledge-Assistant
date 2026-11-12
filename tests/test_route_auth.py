"""Route-auth coverage (Test Strategy 3.1/3.5): enumerate every operation the app publishes, so a
new route that forgets authentication fails here without anyone remembering to write a test.

Routes are enumerated from the OpenAPI document (a stable, public view) rather than FastAPI's
internal route objects, which changed shape between releases. A second test fails if any route
opts out of the schema, because that route would escape the walk.
"""

import re

from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from eka.main import create_app
from tests.helpers import USER_KEY, make_settings, ready_ok

# Routes that are public by design. Anything else must demand a credential.
PUBLIC_PATHS = {"/health/live", "/health/ready"}
_HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
_PLACEHOLDER = "00000000-0000-0000-0000-000000000000"


def _app() -> FastAPI:
    return create_app(make_settings(), readiness_check=ready_ok)


def test_every_non_public_route_requires_a_key() -> None:
    app = _app()
    checked: list[tuple[str, str]] = []
    with TestClient(app, raise_server_exceptions=False) as client:
        for path, operations in app.openapi()["paths"].items():
            if path in PUBLIC_PATHS:
                continue
            url = re.sub(r"\{[^}]+\}", _PLACEHOLDER, path)
            for method in sorted(set(operations) & _HTTP_METHODS):
                response = client.request(method.upper(), url)
                assert response.status_code == 401, f"{method.upper()} {path} needs no key"
                assert response.json()["type"] == "urn:eka:problem:unauthorized"
                checked.append((method, path))
    assert ("get", "/api/v1/me") in checked  # guards against the walk silently checking nothing
    assert {
        ("post", "/api/v1/documents"),
        ("delete", "/api/v1/documents/{document_id}"),
        ("post", "/api/v1/search"),
        ("post", "/api/v1/chat"),
        ("get", "/api/v1/conversations"),
        ("delete", "/api/v1/conversations/{conversation_id}"),
    } <= set(checked)


def test_public_routes_are_exactly_the_declared_ones() -> None:
    published = set(_app().openapi()["paths"])
    assert published >= PUBLIC_PATHS
    assert published - PUBLIC_PATHS == {
        "/api/v1/me",
        "/api/v1/admin/status",
        "/api/v1/admin/metrics",
        "/api/v1/admin/usage",
        "/api/v1/admin/documents",
        "/api/v1/documents",
        "/api/v1/documents/{document_id}",
        "/api/v1/search",
        "/api/v1/chat",
        "/api/v1/conversations",
        "/api/v1/conversations/{conversation_id}",
    }, "a new route: add it to the auth walk"


def test_no_route_hides_from_the_schema() -> None:
    """A route with include_in_schema=False would not be visited by the walk above."""
    hidden: list[str] = []
    for route in _app().routes:
        router = getattr(route, "original_router", None)  # FastAPI wraps included routers
        for inner in getattr(router, "routes", []):
            if isinstance(inner, APIRoute) and not inner.include_in_schema:
                hidden.append(inner.path)
    assert hidden == []


def test_a_valid_key_is_accepted_on_the_protected_route() -> None:
    with TestClient(_app()) as client:
        assert client.get("/api/v1/me", headers={"X-API-Key": USER_KEY}).status_code == 200
