import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from eka.main import create_app
from tests.helpers import make_settings, ready_ok


@pytest.fixture(autouse=True)
def _isolate_from_real_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """A developer's exported EKA_* variables must not change test outcomes."""
    for name in list(os.environ):
        if name.startswith("EKA_"):
            monkeypatch.delenv(name)


@pytest.fixture
def client() -> Iterator[TestClient]:
    """The real app (real auth, real error handler) with a passing readiness check."""
    app = create_app(make_settings(), readiness_check=ready_ok)
    # raise_server_exceptions=False: a 500 must reach us as a response, as it would a client.
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
