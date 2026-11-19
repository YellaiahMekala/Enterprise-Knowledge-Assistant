# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
from fastapi.testclient import TestClient

from eka.main import create_app
from tests.helpers import (
    ADMIN_ID,
    ADMIN_KEY,
    USER_ID,
    USER_KEY,
    capture_logs,
    make_settings,
    ready_ok,
)


def test_me_without_a_key_is_401_problem_json(client: TestClient) -> None:
    response = client.get("/api/v1/me")
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.headers["www-authenticate"] == "ApiKey"
    body = response.json()
    assert body["type"] == "urn:eka:problem:unauthorized"
    assert body["status"] == 401
    assert body["instance"] == "/api/v1/me"


def test_me_with_a_wrong_key_is_401(client: TestClient) -> None:
    assert client.get("/api/v1/me", headers={"X-API-Key": "wrong"}).status_code == 401


def test_me_with_a_user_key_returns_the_caller(client: TestClient) -> None:
    response = client.get("/api/v1/me", headers={"X-API-Key": USER_KEY})
    assert response.status_code == 200
    assert response.json() == {"user_id": USER_ID, "role": "user"}


def test_me_with_an_admin_key_returns_the_admin_role(client: TestClient) -> None:
    response = client.get("/api/v1/me", headers={"X-API-Key": ADMIN_KEY})
    assert response.json() == {"user_id": ADMIN_ID, "role": "admin"}


def test_identity_cannot_be_chosen_by_the_caller(client: TestClient) -> None:
    """A user id in the query or a header is ignored: identity comes from the key alone."""
    response = client.get(
        "/api/v1/me",
        params={"user_id": ADMIN_ID, "owner_id": ADMIN_ID},
        headers={"X-API-Key": USER_KEY, "X-User-Id": ADMIN_ID, "X-Auth-User": ADMIN_ID},
    )
    assert response.json()["user_id"] == USER_ID


def test_the_presented_key_is_never_logged() -> None:
    app = create_app(make_settings(), readiness_check=ready_ok)
    secret = "super-secret-presented-key"
    with capture_logs() as records, TestClient(app) as client:
        client.get("/api/v1/me", headers={"X-API-Key": secret})
        client.get("/api/v1/me", headers={"X-API-Key": USER_KEY})
    assert records, "expected log output to inspect"
    text = " ".join(r.getMessage() for r in records)
    assert secret not in text
    assert USER_KEY not in text


def test_access_log_has_route_template_status_and_user() -> None:
    app = create_app(make_settings(), readiness_check=ready_ok)
    with capture_logs("eka.access") as records, TestClient(app) as client:
        response = client.get("/api/v1/me", headers={"X-API-Key": USER_KEY})
    (record,) = records
    assert record.getMessage() == "GET /api/v1/me 200"
    assert record.route == "/api/v1/me"  # type: ignore[attr-defined]
    assert record.status == 200  # type: ignore[attr-defined]
    assert record.user_id == USER_ID  # type: ignore[attr-defined]
    assert record.request_id == response.headers["x-request-id"]  # type: ignore[attr-defined]
