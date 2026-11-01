"""The readiness probe against a real driver: database up, and database unreachable."""

import asyncio

from fastapi.testclient import TestClient

from eka.main import create_app
from tests.helpers import make_settings

# psycopg's async mode needs a selector loop; Starlette's TestClient otherwise uses the default.
_SELECTOR = {"loop_factory": asyncio.SelectorEventLoop}


def test_ready_is_200_with_a_real_database(migrated_url: str) -> None:
    app = create_app(make_settings(database_url=migrated_url))
    with TestClient(app, backend_options=_SELECTOR) as client:
        response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ready_is_503_when_the_database_is_unreachable() -> None:
    # Nothing listens on port 1: connection refused, as with a stopped database.
    unreachable = "postgresql+psycopg://eka:topsecretpw@127.0.0.1:1/eka"
    app = create_app(make_settings(database_url=unreachable))
    with TestClient(app, backend_options=_SELECTOR, raise_server_exceptions=False) as client:
        ready = client.get("/health/ready")
        live = client.get("/health/live")
    assert ready.status_code == 503
    assert ready.json()["type"] == "urn:eka:problem:unavailable"
    assert "127.0.0.1" not in ready.text
    assert "topsecretpw" not in ready.text
    assert live.status_code == 200  # liveness does not depend on the database
