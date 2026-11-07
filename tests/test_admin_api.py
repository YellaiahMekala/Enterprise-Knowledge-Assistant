from fastapi.testclient import TestClient

from eka.main import create_app
from tests.helpers import ADMIN_KEY, USER_KEY, make_settings, ready_ok


def _client() -> TestClient:
    return TestClient(create_app(make_settings(), readiness_check=ready_ok))


def test_status_is_for_admins_only() -> None:
    client = _client()
    assert client.get("/api/v1/admin/status").status_code == 401
    assert client.get("/api/v1/admin/status", headers={"X-API-Key": USER_KEY}).status_code == 403
    response = client.get("/api/v1/admin/status", headers={"X-API-Key": ADMIN_KEY})
    assert response.status_code == 200
    assert {"version", "environment", "uptime_seconds"} <= response.json().keys()


def test_metrics_are_for_admins_only() -> None:
    client = _client()
    assert client.get("/api/v1/admin/metrics").status_code == 401
    assert client.get("/api/v1/admin/metrics", headers={"X-API-Key": USER_KEY}).status_code == 403


def test_metrics_count_requests_by_route_template_not_raw_path() -> None:
    client = _client()
    client.get("/api/v1/me", headers={"X-API-Key": USER_KEY})
    client.get("/api/v1/me", headers={"X-API-Key": "wrong"})
    client.get(
        "/api/v1/documents/00000000-0000-0000-0000-000000000000", headers={"X-API-Key": "wrong"}
    )

    body = client.get("/api/v1/admin/metrics", headers={"X-API-Key": ADMIN_KEY}).text

    assert 'eka_http_requests_total{method="GET",route="/api/v1/me",status="200"} 1.0' in body
    assert 'route="/api/v1/me",status="401"} 1.0' in body
    assert "/api/v1/documents/{document_id}" in body
    assert "00000000-0000-0000-0000-000000000000" not in body


def test_health_probes_are_not_counted() -> None:
    client = _client()
    client.get("/health/live")
    body = client.get("/api/v1/admin/metrics", headers={"X-API-Key": ADMIN_KEY}).text
    assert "/health" not in body
