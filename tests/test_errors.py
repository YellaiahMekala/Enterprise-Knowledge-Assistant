"""Every failure has one shape: problem+json with a request id, and no internals."""

import re

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from eka.domain.errors import NotFound
from eka.main import create_app
from tests.helpers import capture_logs, make_settings, ready_ok

_FIELDS = {"type", "title", "status", "detail", "instance", "request_id"}


def _assert_problem(response_json: dict[str, object], status: int, slug: str) -> None:
    assert set(response_json) >= _FIELDS
    assert response_json["status"] == status
    assert response_json["type"] == f"urn:eka:problem:{slug}"


def test_unknown_route_uses_the_problem_shape(client: TestClient) -> None:
    response = client.get("/no-such-route")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    _assert_problem(response.json(), 404, "not-found")
    assert response.json()["request_id"] == response.headers["x-request-id"]


def test_wrong_method_uses_the_problem_shape_and_keeps_allow(client: TestClient) -> None:
    response = client.post("/health/live")
    assert response.status_code == 405
    _assert_problem(response.json(), 405, "method-not-allowed")
    assert "GET" in response.headers["allow"]


def test_request_ids_are_unique_and_inbound_ids_are_ignored(client: TestClient) -> None:
    first = client.get("/health/live", headers={"X-Request-Id": "attacker\nforged"})
    second = client.get("/health/live")
    assert first.headers["x-request-id"] != second.headers["x-request-id"]
    assert "attacker" not in first.headers["x-request-id"]
    assert re.fullmatch(r"[0-9a-f]{32}", first.headers["x-request-id"])


class _Body(BaseModel):
    count: int


def _app_with_failing_routes() -> FastAPI:
    app = create_app(make_settings(), readiness_check=ready_ok)

    @app.post("/_test/validate")
    async def validate(body: _Body) -> dict[str, int]:
        return {"count": body.count}

    @app.get("/_test/boom")
    async def boom() -> None:
        raise RuntimeError("secret internal detail: /var/lib/db password=hunter2")

    @app.get("/_test/missing")
    async def missing() -> None:
        raise NotFound("document 7 of user bob")

    return app


def test_validation_error_is_422_without_echoing_the_input() -> None:
    with TestClient(_app_with_failing_routes(), raise_server_exceptions=False) as client:
        response = client.post("/_test/validate", json={"count": "SENSITIVE-VALUE"})
    assert response.status_code == 422
    body = response.json()
    _assert_problem(body, 422, "validation")
    assert body["errors"][0]["loc"] == ["body", "count"]
    assert "SENSITIVE-VALUE" not in response.text


def test_unexpected_error_is_a_generic_500_and_the_detail_is_logged() -> None:
    with (
        capture_logs() as records,
        TestClient(_app_with_failing_routes(), raise_server_exceptions=False) as client,
    ):
        response = client.get("/_test/boom")
    assert response.status_code == 500
    _assert_problem(response.json(), 500, "internal")
    assert "hunter2" not in response.text
    assert "/var/lib/db" not in response.text
    assert response.headers["x-request-id"] == response.json()["request_id"]
    errors = [r for r in records if r.levelname == "ERROR"]
    assert errors
    assert errors[0].exc_info is not None
    assert "hunter2" in str(errors[0].exc_info[1])  # the detail is in the log, not the response


def test_not_found_error_hides_the_message() -> None:
    with TestClient(_app_with_failing_routes(), raise_server_exceptions=False) as client:
        response = client.get("/_test/missing")
    assert response.status_code == 404
    assert "bob" not in response.text
    assert response.json()["detail"] == "No such resource."
