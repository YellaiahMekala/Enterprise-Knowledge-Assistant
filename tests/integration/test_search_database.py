# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""Retrieval against real PostgreSQL with pgvector, including the HTTP endpoint."""

import asyncio
import uuid

import numpy as np
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from eka.adapters.db.engine import Database
from eka.adapters.db.search import SqlChunkSearch
from eka.domain.models import Role, SearchFilters, SearchHit
from eka.main import create_app
from eka.services.retrieval import RetrievalService, RetrievalSettings
from tests.fakes import FakeEmbedder
from tests.helpers import USER_KEY, make_settings
from tests.integration.helpers import admin_engine, run_async

_SELECTOR = {"loop_factory": asyncio.SelectorEventLoop}
EMBED = FakeEmbedder()


def _vector(text_value: str) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in EMBED.embed_documents([text_value])[0]) + "]"


def seed(
    engine: Engine, owner: str, filename: str, passages: list[str], content_type: str = "text/plain"
) -> uuid.UUID:
    document_id = uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO documents (id, owner_id, filename, content_type, size_bytes, sha256, "
                "storage_key, status) VALUES (:id, :owner, :name, :type, 1, :sha, :key, 'ready')"
            ),
            {
                "id": document_id,
                "owner": owner,
                "name": filename,
                "type": content_type,
                "sha": uuid.uuid4().hex * 2,
                "key": f"{owner}/{document_id}",
            },
        )
        for ordinal, passage in enumerate(passages):
            connection.execute(
                text(
                    "INSERT INTO chunks (id, document_id, owner_id, ordinal, text, locator, "
                    "char_start, char_end, token_count, embedding, embedding_model, chunk_config) "
                    "VALUES (:id, :doc, :owner, :ordinal, :body, CAST(:locator AS jsonb), 0, 1, 1, "
                    "CAST(:vector AS vector), 'fake-embedder', 'test')"
                ),
                {
                    "id": uuid.uuid4(),
                    "doc": document_id,
                    "owner": owner,
                    "ordinal": ordinal,
                    "body": passage,
                    "locator": f'{{"type": "page", "page": {ordinal + 1}}}',
                    "vector": _vector(passage),
                },
            )
    return document_id


def search_as(
    url: str, owner: str, question: str, *, top_k: int = 5, filters: SearchFilters | None = None
) -> list[SearchHit]:
    async def scenario() -> list[SearchHit]:
        database = Database(url)
        try:
            async with database.session_for(owner, Role.USER) as session:
                service = RetrievalService(
                    SqlChunkSearch(session), EMBED, RetrievalSettings(candidates=10)
                )
                return await service.search(
                    owner, question, top_k=top_k, filters=filters or SearchFilters()
                )
        finally:
            await database.dispose()

    return run_async(scenario)


def test_each_owner_sees_only_their_own_passages(isolated_url: str) -> None:
    engine = admin_engine(isolated_url)
    alice, bob = f"alice-{uuid.uuid4().hex[:6]}", f"bob-{uuid.uuid4().hex[:6]}"
    seed(engine, alice, "leave.md", ["Staff may carry over five unused leave days."])
    seed(engine, bob, "bob-leave.md", ["Contractors may carry over leave days as well."])

    hits = search_as(isolated_url, alice, "carry over leave days")
    assert hits and {h.filename for h in hits} == {"leave.md"}
    assert all("Contractors" not in h.text for h in hits)

    bob_hits = search_as(isolated_url, bob, "carry over leave days")
    assert {h.filename for h in bob_hits} == {"bob-leave.md"}


def test_a_stranger_with_no_documents_gets_nothing(isolated_url: str) -> None:
    engine = admin_engine(isolated_url)
    seed(engine, f"owner-{uuid.uuid4().hex[:6]}", "a.txt", ["secret plan details"])
    assert search_as(isolated_url, f"stranger-{uuid.uuid4().hex[:6]}", "secret plan") == []


def test_filters_by_document_and_type(isolated_url: str) -> None:
    engine = admin_engine(isolated_url)
    owner = f"owner-{uuid.uuid4().hex[:6]}"
    pdf = seed(engine, owner, "policy.pdf", ["Travel must be booked early."], "application/pdf")
    seed(engine, owner, "notes.txt", ["Travel must be booked early too."], "text/plain")

    by_type = search_as(
        isolated_url,
        owner,
        "travel booked",
        filters=SearchFilters(content_types=("application/pdf",)),
    )
    assert {h.filename for h in by_type} == {"policy.pdf"}

    by_id = search_as(
        isolated_url, owner, "travel booked", filters=SearchFilters(document_ids=(pdf,))
    )
    assert {h.filename for h in by_id} == {"policy.pdf"}


def test_the_sparse_path_finds_exact_terms_the_vectors_might_miss(isolated_url: str) -> None:
    engine = admin_engine(isolated_url)
    owner = f"owner-{uuid.uuid4().hex[:6]}"
    seed(engine, owner, "codes.txt", ["Error code E-4017 means the card was declined."])
    seed(engine, owner, "other.txt", ["The office opens at nine every weekday."])
    hits = search_as(isolated_url, owner, "what does E-4017 mean")
    assert hits and hits[0].filename == "codes.txt"
    assert hits[0].fused > 0 and hits[0].cosine > -1.0


def test_the_cosine_reported_matches_the_stored_vectors(isolated_url: str) -> None:
    engine = admin_engine(isolated_url)
    owner = f"owner-{uuid.uuid4().hex[:6]}"
    passages = ["Staff may carry over five unused leave days.", "The canteen opens at noon."]
    seed(engine, owner, "mixed.txt", passages)
    question = "how many leave days carry over"
    hits = search_as(isolated_url, owner, question)
    query = np.asarray(EMBED.embed_query(question))
    for hit in hits:
        stored = np.asarray(EMBED.embed_documents([hit.text])[0])
        assert abs(hit.cosine - float(query @ stored)) < 1e-4


def test_the_endpoint_authenticates_and_scopes_the_search(isolated_url: str) -> None:
    engine = admin_engine(isolated_url)
    alice = "alice"  # user id of USER_KEY
    seed(engine, alice, "endpoint.txt", ["Staff may carry over five unused leave days."])
    app = create_app(
        make_settings(database_url=isolated_url), readiness_check=_ready, embedder=EMBED
    )
    with TestClient(app, backend_options=_SELECTOR, raise_server_exceptions=False) as client:
        assert client.post("/api/v1/search", json={"query": "leave"}).status_code == 401
        response = client.post(
            "/api/v1/search",
            headers={"X-API-Key": USER_KEY},
            json={"query": "carry over leave days", "top_k": 3},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["query"] == "carry over leave days"
        assert body["results"][0]["filename"] == "endpoint.txt"
        assert set(body["results"][0]["scores"]) == {"fused", "cosine", "rerank"}
        assert body["results"][0]["scores"]["rerank"] is None
        empty = client.post(
            "/api/v1/search",
            headers={"X-API-Key": USER_KEY},
            json={"query": "leave", "filters": {"content_types": ["application/pdf"]}},
        )
        assert empty.json()["results"] == []
        bad = client.post("/api/v1/search", headers={"X-API-Key": USER_KEY}, json={"query": ""})
        assert bad.status_code == 422


async def _ready() -> None:
    """Readiness check that always passes."""
