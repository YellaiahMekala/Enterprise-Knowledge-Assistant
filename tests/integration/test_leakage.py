# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""Leakage suite (Test Strategy 3.4): two users with overlapping topics, every read path, through
the real HTTP API and a real database. Nothing of one user may appear for another.

Seeding is done as the superuser (it bypasses row-level security by design); every assertion goes
through the API with a different caller's key.
"""

import asyncio
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from eka.config import ApiKeyEntry
from eka.domain.models import Role
from eka.main import create_app
from eka.security.auth import digest_key
from tests.fakes import FakeEmbedder
from tests.helpers import ADMIN_ID, ADMIN_KEY, USER_ID, USER_KEY, api_keys, make_settings, ready_ok
from tests.integration.helpers import admin_engine
from tests.integration.test_search_database import seed

_SELECTOR = {"loop_factory": asyncio.SelectorEventLoop}
BOB_ID = "bob"
BOB_KEY = "test-bob-key-0003"

ALICE_TEXT = "Alice staff may carry over five unused leave days into the next year."
BOB_TEXT = "Bob contractors may carry over two unused leave days into the next year."
ALICE_ONLY = "Alice confidential merger codename Falcon."


class World:
    def __init__(self, client: TestClient, alice_doc: uuid.UUID, bob_doc: uuid.UUID) -> None:
        self.client = client
        self.alice_doc = alice_doc
        self.bob_doc = bob_doc

    def search(self, key: str, query: str, **filters: Any) -> list[dict[str, Any]]:
        body: dict[str, Any] = {"query": query, "top_k": 20}
        if filters:
            body["filters"] = filters
        response = self.client.post("/api/v1/search", headers={"X-API-Key": key}, json=body)
        assert response.status_code == 200, response.text
        results: list[dict[str, Any]] = response.json()["results"]
        return results


@pytest.fixture
def world(isolated_url: str) -> Iterator[World]:
    engine = admin_engine(isolated_url)
    alice_doc = seed(engine, USER_ID, "alice-leave.md", [ALICE_TEXT, ALICE_ONLY])
    bob_doc = seed(engine, BOB_ID, "bob-leave.md", [BOB_TEXT])
    keys = {**api_keys(), BOB_ID: ApiKeyEntry(sha256=digest_key(BOB_KEY).hex(), role=Role.USER)}
    app = create_app(
        make_settings(database_url=isolated_url, api_keys=keys),
        readiness_check=ready_ok,
        embedder=FakeEmbedder(),
    )
    with TestClient(app, backend_options=_SELECTOR, raise_server_exceptions=False) as client:
        yield World(client, alice_doc, bob_doc)


def test_search_returns_only_the_callers_passages_for_overlapping_topics(world: World) -> None:
    for key, own_file, other_text in (
        (USER_KEY, "alice-leave.md", "Bob"),
        (BOB_KEY, "bob-leave.md", "Alice"),
    ):
        results = world.search(key, "carry over unused leave days")
        assert results
        assert {r["filename"] for r in results} == {own_file}
        assert all(other_text not in r["text"] for r in results)


def test_a_phrase_that_exists_only_for_one_user_finds_nothing_for_the_other(world: World) -> None:
    assert world.search(USER_KEY, "merger codename Falcon")[0]["text"] == ALICE_ONLY
    assert all("Falcon" not in r["text"] for r in world.search(BOB_KEY, "merger codename Falcon"))


def test_filtering_by_another_users_document_id_returns_nothing(world: World) -> None:
    assert world.search(BOB_KEY, "leave days", document_ids=[str(world.alice_doc)]) == []


def test_a_mixed_document_filter_still_returns_only_the_callers_own(world: World) -> None:
    ids = [str(world.alice_doc), str(world.bob_doc)]
    results = world.search(BOB_KEY, "leave days", document_ids=ids)
    assert results and {r["document_id"] for r in results} == {str(world.bob_doc)}


def test_returned_ids_never_belong_to_the_other_user(world: World) -> None:
    alice_ids = {r["chunk_id"] for r in world.search(USER_KEY, "leave days")}
    bob_ids = {r["chunk_id"] for r in world.search(BOB_KEY, "leave days")}
    assert alice_ids and bob_ids and not alice_ids & bob_ids


def test_listing_shows_only_the_callers_documents(world: World) -> None:
    response = world.client.get("/api/v1/documents", headers={"X-API-Key": BOB_KEY})
    assert response.status_code == 200
    assert {d["id"] for d in response.json()["items"]} == {str(world.bob_doc)}


def test_reading_another_users_document_is_indistinguishable_from_unknown(world: World) -> None:
    headers = {"X-API-Key": BOB_KEY}
    other = world.client.get(f"/api/v1/documents/{world.alice_doc}", headers=headers)
    unknown = world.client.get(f"/api/v1/documents/{uuid.uuid4()}", headers=headers)
    assert other.status_code == unknown.status_code == 404
    assert other.json()["detail"] == unknown.json()["detail"]
    assert other.json()["type"] == unknown.json()["type"]


def test_deleting_another_users_document_fails_and_changes_nothing(world: World) -> None:
    response = world.client.delete(
        f"/api/v1/documents/{world.alice_doc}", headers={"X-API-Key": BOB_KEY}
    )
    assert response.status_code == 404
    still_there = world.client.get(
        f"/api/v1/documents/{world.alice_doc}", headers={"X-API-Key": USER_KEY}
    )
    assert still_there.status_code == 200
    assert world.search(USER_KEY, "carry over unused leave days")


def test_an_admin_cannot_read_passages_of_other_users(world: World) -> None:
    """Admins may see document metadata (ADR-012) but have no policy on chunks."""
    assert world.search(ADMIN_KEY, "carry over unused leave days") == []
    assert world.search(ADMIN_KEY, "leave days", document_ids=[str(world.alice_doc)]) == []
    assert ADMIN_ID not in {USER_ID, BOB_ID}
