# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""The documents endpoints through the real app, auth and error handling, with in-memory doubles
behind the service (the database path is covered by the integration tests)."""

import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient

from eka.domain.models import Role
from eka.main import create_app
from eka.services.documents import DocumentService, UploadPolicy
from tests.fakes import InMemoryDocumentRepository, InMemoryFileStore
from tests.files import make_pdf
from tests.helpers import ADMIN_KEY, USER_KEY, make_settings, ready_ok

POLICY = UploadPolicy(
    max_upload_bytes=20_000,
    max_documents=3,
    text_extensions=(".java", ".txt"),
    max_text_bytes=5_000,
)
USER = {"X-API-Key": USER_KEY}
OTHER = {"X-API-Key": ADMIN_KEY}  # a different user id
PDF = ("a.pdf", make_pdf(["hello world"]), "application/pdf")


@pytest.fixture
def stores() -> tuple[InMemoryDocumentRepository, InMemoryFileStore]:
    return InMemoryDocumentRepository(), InMemoryFileStore()


@pytest.fixture
def client(stores: tuple[InMemoryDocumentRepository, InMemoryFileStore]) -> Iterator[TestClient]:
    repository, store = stores
    app = create_app(make_settings(), readiness_check=ready_ok)

    def factory(owner_id: str, role: Role) -> AbstractAsyncContextManager[DocumentService]:
        @asynccontextmanager
        async def scope() -> AsyncIterator[DocumentService]:
            yield DocumentService(repository, store, POLICY)

        return scope()

    app.state.document_service_factory = factory
    app.state.max_upload_bytes = POLICY.max_upload_bytes
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def upload(
    client: TestClient,
    headers: dict[str, str] = USER,
    file: tuple[str, bytes, str | None] = PDF,
) -> Any:
    return client.post("/api/v1/documents", headers=headers, files={"file": file})


def test_a_new_upload_is_accepted_with_a_location_and_pending_status(client: TestClient) -> None:
    response = upload(client)
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending" and body["filename"] == "a.pdf"
    assert response.headers["location"] == f"/api/v1/documents/{body['id']}"
    assert "storage_key" not in body and "sha256" not in body  # internals are not exposed


def test_the_same_bytes_again_are_200_with_the_same_document(client: TestClient) -> None:
    first = upload(client).json()
    again = upload(client)
    assert again.status_code == 200
    assert again.json()["id"] == first["id"]
    assert "location" not in again.headers


def test_unsupported_and_mismatched_files_are_415_with_a_reason(client: TestClient) -> None:
    exe = upload(client, file=("tool.exe", b"MZ", "application/octet-stream"))
    assert exe.status_code == 415
    assert exe.headers["content-type"].startswith("application/problem+json")
    assert exe.json()["reason"] == "unsupported_type"
    fake = upload(client, file=("fake.pdf", b"MZ not a pdf", "application/pdf"))
    assert fake.status_code == 415 and fake.json()["reason"] == "type_mismatch"


def test_an_oversized_file_is_413(client: TestClient) -> None:
    big = ("big.pdf", b"%PDF-" + b"0" * 30_000, "application/pdf")
    response = upload(client, file=big)
    assert response.status_code == 413
    assert response.json()["type"] == "urn:eka:problem:payload-too-large"


def test_the_quota_is_403(client: TestClient) -> None:
    for index in range(3):
        assert (
            upload(client, file=(f"{index}.pdf", make_pdf([f"d{index}"]), None)).status_code == 202
        )
    response = upload(client, file=("x.pdf", make_pdf(["extra"]), None))
    assert response.status_code == 403
    assert response.json()["type"] == "urn:eka:problem:quota-exceeded"


def test_a_missing_file_field_is_422(client: TestClient) -> None:
    response = client.post("/api/v1/documents", headers=USER)
    assert response.status_code == 422
    assert response.json()["type"] == "urn:eka:problem:validation"


def test_another_users_document_is_404_everywhere(client: TestClient) -> None:
    document_id = upload(client).json()["id"]
    assert client.get(f"/api/v1/documents/{document_id}", headers=USER).status_code == 200
    assert client.get(f"/api/v1/documents/{document_id}", headers=OTHER).status_code == 404
    assert client.delete(f"/api/v1/documents/{document_id}", headers=OTHER).status_code == 404
    assert client.get("/api/v1/documents", headers=OTHER).json()["items"] == []
    assert client.get(f"/api/v1/documents/{document_id}", headers=USER).status_code == 200


def test_get_unknown_and_malformed_ids(client: TestClient) -> None:
    assert client.get(f"/api/v1/documents/{uuid.uuid4()}", headers=USER).status_code == 404
    assert client.get("/api/v1/documents/not-a-uuid", headers=USER).status_code == 422


def test_delete_returns_204_removes_the_document_and_the_file(
    client: TestClient, stores: tuple[InMemoryDocumentRepository, InMemoryFileStore]
) -> None:
    document_id = upload(client).json()["id"]
    assert len(stores[1].objects) == 1
    response = client.delete(f"/api/v1/documents/{document_id}", headers=USER)
    assert response.status_code == 204 and response.content == b""
    assert client.get(f"/api/v1/documents/{document_id}", headers=USER).status_code == 404
    assert stores[1].objects == {}


def test_list_paginates_and_filters_and_validates_its_parameters(client: TestClient) -> None:
    for index in range(3):
        upload(client, file=(f"{index}.pdf", make_pdf([f"d{index}"]), None))
    page = client.get("/api/v1/documents?limit=2&offset=0", headers=USER).json()
    assert len(page["items"]) == 2 and page["limit"] == 2 and page["offset"] == 0
    rest = client.get("/api/v1/documents?limit=2&offset=2", headers=USER).json()
    assert len(rest["items"]) == 1
    assert client.get("/api/v1/documents?status=ready", headers=USER).json()["items"] == []
    assert client.get("/api/v1/documents?limit=101", headers=USER).status_code == 422
    assert client.get("/api/v1/documents?limit=0", headers=USER).status_code == 422
    assert client.get("/api/v1/documents?offset=-1", headers=USER).status_code == 422
    assert client.get("/api/v1/documents?status=nope", headers=USER).status_code == 422


def test_every_document_route_requires_a_key(client: TestClient) -> None:
    assert client.get("/api/v1/documents").status_code == 401
    assert client.post("/api/v1/documents", files={"file": PDF}).status_code == 401
    assert client.get(f"/api/v1/documents/{uuid.uuid4()}").status_code == 401
    assert client.delete(f"/api/v1/documents/{uuid.uuid4()}").status_code == 401


def test_without_a_database_the_routes_answer_503_not_500() -> None:
    app = create_app(make_settings(), readiness_check=ready_ok)  # no database_url configured
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/v1/documents", headers=USER)
    assert response.status_code == 503
    assert response.json()["type"] == "urn:eka:problem:unavailable"
