"""Delivery files stay consistent with the tests and carry no secrets."""

import re
from pathlib import Path

from tests.integration.helpers import PGVECTOR_IMAGE

ROOT = Path(__file__).resolve().parents[1]


def _compose() -> str:
    return (ROOT / "docker-compose.yml").read_text(encoding="utf-8")


def test_compose_database_image_matches_the_one_the_tests_use() -> None:
    match = re.search(r"^\s+image:\s*(pgvector/pgvector:\S+)\s*$", _compose(), re.MULTILINE)
    assert match, "db service must use the pgvector image"
    assert match.group(1) == PGVECTOR_IMAGE


def test_the_database_image_tag_is_pinned_to_exact_versions() -> None:
    assert re.fullmatch(r"pgvector/pgvector:\d+\.\d+\.\d+-pg\d+", PGVECTOR_IMAGE), (
        "pin pgvector and PostgreSQL versions; a floating tag changes under you"
    )


def test_compose_holds_no_literal_secrets() -> None:
    compose = _compose()
    for name in ("POSTGRES_PASSWORD", "EKA_API_KEYS", "EKA_DATABASE_URL"):
        for line in (ln for ln in compose.splitlines() if name in ln):
            assert "${" in line, f"{name} must come from the environment, not a literal: {line}"


def test_the_example_env_file_has_placeholders_not_values() -> None:
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert re.search(r"^EKA_DB_PASSWORD=$", example, re.MULTILINE)
    assert "<64 hex characters>" in example
    assert not re.search(r"[0-9a-f]{64}", example), "no real digest in the example"


def test_the_real_env_file_is_ignored_by_git() -> None:
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in ignored
