# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
from fastapi.testclient import TestClient

from eka.main import create_app
from tests.helpers import make_settings, ready_ok

# Outside environment=test the settings insist on these; the URL is never connected to here.
_LOCAL = {"environment": "local", "database_url": "postgresql+psycopg://u:p@127.0.0.1:1/x"}


def test_api_docs_served_outside_prod() -> None:
    app = create_app(make_settings(**_LOCAL), readiness_check=ready_ok)
    with TestClient(app) as client:
        assert client.get("/docs").status_code == 200
        assert client.get("/openapi.json").status_code == 200


def test_api_docs_hidden_in_prod() -> None:
    app = create_app(make_settings(**{**_LOCAL, "environment": "prod"}), readiness_check=ready_ok)
    with TestClient(app) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404
