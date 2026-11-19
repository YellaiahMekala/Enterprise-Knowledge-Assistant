# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""Upload use case with in-memory doubles: validation order, idempotency, quota, clean-up."""

import hashlib
import uuid

import pytest

from eka.domain.errors import NotFound, PayloadTooLarge, QuotaExceeded, UnsupportedMedia
from eka.domain.models import DocumentStatus
from eka.services.documents import DocumentService, UploadPolicy
from tests.fakes import InMemoryDocumentRepository, InMemoryFileStore
from tests.files import make_pdf

POLICY = UploadPolicy(
    max_upload_bytes=50_000,
    max_documents=3,
    text_extensions=(".java", ".txt"),
    max_text_bytes=10_000,
)


def build(
    policy: UploadPolicy = POLICY,
) -> tuple[DocumentService, InMemoryDocumentRepository, InMemoryFileStore]:
    repository, store = InMemoryDocumentRepository(), InMemoryFileStore()
    return DocumentService(repository, store, policy), repository, store


@pytest.mark.anyio
async def test_upload_stores_the_file_and_queues_a_pending_document() -> None:
    service, repository, store = build()
    data = make_pdf(["hello"])
    document, created = await service.upload("alice", "../../policy.pdf", "application/pdf", data)
    assert created is True
    assert document.status is DocumentStatus.PENDING
    assert document.filename == "policy.pdf"  # the path part never survives
    assert document.sha256 == hashlib.sha256(data).hexdigest()
    assert document.storage_key == f"alice/{document.id}"  # the user's file name is not in the key
    assert store.objects[document.storage_key] == data
    assert document.id in repository.rows


@pytest.mark.anyio
async def test_the_same_bytes_twice_return_the_existing_document_and_store_nothing_new() -> None:
    service, _, store = build()
    data = make_pdf(["hello"])
    first, created_first = await service.upload("alice", "a.pdf", None, data)
    second, created_second = await service.upload("alice", "renamed.pdf", None, data)
    assert (created_first, created_second) == (True, False)
    assert second.id == first.id
    assert len(store.objects) == 1


@pytest.mark.anyio
async def test_two_users_may_upload_the_same_bytes_independently() -> None:
    service, _, store = build()
    data = make_pdf(["shared"])
    a, _ = await service.upload("alice", "a.pdf", None, data)
    b, created = await service.upload("bob", "a.pdf", None, data)
    assert created is True and a.id != b.id
    assert len(store.objects) == 2


@pytest.mark.anyio
async def test_rejections_happen_before_anything_is_stored() -> None:
    service, repository, store = build()
    with pytest.raises(PayloadTooLarge):
        await service.upload("alice", "big.pdf", None, b"%PDF-" + b"0" * 60_000)
    with pytest.raises(UnsupportedMedia):
        await service.upload("alice", "tool.exe", None, b"MZ")
    with pytest.raises(UnsupportedMedia):
        await service.upload("alice", "fake.pdf", None, b"MZ not a pdf")
    assert store.objects == {} and repository.rows == {}


@pytest.mark.anyio
async def test_the_quota_blocks_new_documents_but_not_a_repeat_upload() -> None:
    service, _, _ = build()
    for index in range(3):
        await service.upload("alice", f"{index}.pdf", None, make_pdf([f"doc {index}"]))
    with pytest.raises(QuotaExceeded):
        await service.upload("alice", "4.pdf", None, make_pdf(["one too many"]))
    again, created = await service.upload("alice", "0.pdf", None, make_pdf(["doc 0"]))
    assert created is False  # a duplicate is not a new document, so the quota does not apply
    await service.upload("bob", "x.pdf", None, make_pdf(["bob is unaffected"]))


@pytest.mark.anyio
async def test_a_failed_database_write_removes_the_stored_file() -> None:
    service, repository, store = build()
    repository.fail_add_after_insert = True
    with pytest.raises(RuntimeError):
        await service.upload("alice", "a.pdf", None, make_pdf(["x"]))
    assert store.objects == {}


@pytest.mark.anyio
async def test_get_and_delete_are_scoped_to_the_owner() -> None:
    service, repository, store = build()
    document, _ = await service.upload("alice", "a.pdf", None, make_pdf(["x"]))
    assert (await service.get("alice", document.id)).id == document.id
    with pytest.raises(NotFound):
        await service.get("bob", document.id)
    with pytest.raises(NotFound):
        await service.delete("bob", document.id)
    assert document.id in repository.rows and document.storage_key in store.objects
    await service.delete("alice", document.id)
    assert repository.rows == {} and store.objects == {}
    with pytest.raises(NotFound):
        await service.delete("alice", document.id)
    with pytest.raises(NotFound):
        await service.get("alice", uuid.uuid4())


@pytest.mark.anyio
async def test_list_returns_only_the_owners_documents_filtered_by_status() -> None:
    service, repository, _ = build()
    mine, _ = await service.upload("alice", "a.pdf", None, make_pdf(["a"]))
    await service.upload("bob", "b.pdf", None, make_pdf(["b"]))
    assert [d.id for d in await service.list("alice")] == [mine.id]
    assert await service.list("alice", status=DocumentStatus.READY) == []
    assert len(repository.rows) == 2
