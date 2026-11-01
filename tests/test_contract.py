"""Contract drift (ADR-019): the committed OpenAPI snapshot must match what the code generates."""

import json

from eka.tools.export_openapi import SNAPSHOT_PATH, build_openapi, main, render


def test_openapi_snapshot_matches_the_code() -> None:
    assert SNAPSHOT_PATH.exists(), "run: python -m eka.tools.export_openapi"
    assert SNAPSHOT_PATH.read_text(encoding="utf-8") == render(build_openapi()), (
        "docs/openapi.json is out of date. If the change is intended, run: "
        "python -m eka.tools.export_openapi"
    )


def test_check_mode_succeeds_when_the_snapshot_is_current() -> None:
    assert main(["--check"]) == 0


def test_the_snapshot_documents_the_contract() -> None:
    schema = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    assert {"/api/v1/me", "/health/live", "/health/ready"} <= set(schema["paths"])
    scheme = schema["components"]["securitySchemes"]["APIKeyHeader"]
    assert (scheme["type"], scheme["in"], scheme["name"]) == ("apiKey", "header", "X-API-Key")
    assert "401" in schema["paths"]["/api/v1/me"]["get"]["responses"]
    assert "503" in schema["paths"]["/health/ready"]["get"]["responses"]


def test_building_the_schema_is_deterministic() -> None:
    assert render(build_openapi()) == render(build_openapi())
