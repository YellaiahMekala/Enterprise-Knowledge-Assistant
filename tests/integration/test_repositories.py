"""Document repository against a real database, through the same row-level-security session the
API uses."""

import pytest

from eka.adapters.db.engine import Database
from eka.adapters.db.repositories import SqlDocumentRepository
from eka.domain.models import DocumentStatus, Role
from tests.integration.helpers import (
    admin_engine,
    count,
    new_document,
    run_async,
    seed_chunk,
    unique_owner,
)


def test_add_persists_the_document_with_defaults(migrated_url: str) -> None:
    owner = unique_owner()
    new = new_document("policy.pdf")

    async def scenario() -> tuple[object, bool]:
        database = Database(migrated_url)
        try:
            async with database.session_for(owner, Role.USER) as session:
                return await SqlDocumentRepository(session).add(owner, new)
        finally:
            await database.dispose()

    document, created = run_async(scenario)
    assert created is True
    assert document.id == new.id  # type: ignore[attr-defined]
    assert document.owner_id == owner  # type: ignore[attr-defined]
    assert document.status is DocumentStatus.PENDING  # type: ignore[attr-defined]
    assert document.attempts == 0  # type: ignore[attr-defined]
    assert document.filename == "policy.pdf"  # type: ignore[attr-defined]


def test_identical_bytes_by_the_same_owner_return_the_existing_document(migrated_url: str) -> None:
    owner = unique_owner()
    first, second = new_document("a.pdf", sha="a" * 64), new_document("b.pdf", sha="a" * 64)

    async def scenario() -> tuple[tuple[object, bool], tuple[object, bool]]:
        database = Database(migrated_url)
        try:
            async with database.session_for(owner, Role.USER) as session:
                repository = SqlDocumentRepository(session)
                return await repository.add(owner, first), await repository.add(owner, second)
        finally:
            await database.dispose()

    (doc1, created1), (doc2, created2) = run_async(scenario)
    assert (created1, created2) == (True, False)
    assert doc2.id == doc1.id == first.id  # type: ignore[attr-defined]
    assert doc2.filename == "a.pdf"  # type: ignore[attr-defined]  # the first upload is kept
    assert count(admin_engine(migrated_url), "documents", "owner_id = :o", o=owner) == 1


def test_the_same_bytes_from_two_owners_are_two_documents(migrated_url: str) -> None:
    alice, bob = unique_owner("alice"), unique_owner("bob")
    sha = "b" * 64

    async def scenario() -> tuple[bool, bool]:
        database = Database(migrated_url)
        try:
            async with database.session_for(alice, Role.USER) as session:
                _, created_a = await SqlDocumentRepository(session).add(
                    alice, new_document(sha=sha)
                )
            async with database.session_for(bob, Role.USER) as session:
                _, created_b = await SqlDocumentRepository(session).add(bob, new_document(sha=sha))
            return created_a, created_b
        finally:
            await database.dispose()

    assert run_async(scenario) == (True, True)


def test_get_returns_own_documents_and_none_for_foreign_ids(migrated_url: str) -> None:
    alice, bob = unique_owner("alice"), unique_owner("bob")
    mine = new_document()

    async def scenario() -> tuple[object, object]:
        database = Database(migrated_url)
        try:
            async with database.session_for(alice, Role.USER) as session:
                await SqlDocumentRepository(session).add(alice, mine)
            async with database.session_for(alice, Role.USER) as session:
                own = await SqlDocumentRepository(session).get(alice, mine.id)
            async with database.session_for(bob, Role.USER) as session:
                foreign = await SqlDocumentRepository(session).get(bob, mine.id)
            return own, foreign
        finally:
            await database.dispose()

    own, foreign = run_async(scenario)
    assert own is not None
    assert foreign is None


def test_list_is_newest_first_filtered_by_status_and_paged(migrated_url: str) -> None:
    owner = unique_owner()
    docs = [new_document(f"{i}.pdf") for i in range(5)]

    async def scenario() -> tuple[list[str], list[str], list[str], int]:
        database = Database(migrated_url)
        try:
            for doc in docs:  # separate transactions so created_at (now()) differs
                async with database.session_for(owner, Role.USER) as session:
                    await SqlDocumentRepository(session).add(owner, doc)
            async with database.session_for(owner, Role.USER) as session:
                repository = SqlDocumentRepository(session)
                everything = [d.filename for d in await repository.list_by_owner(owner)]
                page = [
                    d.filename for d in await repository.list_by_owner(owner, limit=2, offset=1)
                ]
                ready = [
                    d.filename
                    for d in await repository.list_by_owner(owner, status=DocumentStatus.READY)
                ]
                pending = len(await repository.list_by_owner(owner, status=DocumentStatus.PENDING))
            return everything, page, ready, pending
        finally:
            await database.dispose()

    everything, page, ready, pending = run_async(scenario)
    assert everything == ["4.pdf", "3.pdf", "2.pdf", "1.pdf", "0.pdf"]
    assert page == ["3.pdf", "2.pdf"]
    assert ready == []
    assert pending == 5


def test_delete_removes_the_document_and_its_chunks_by_cascade(migrated_url: str) -> None:
    owner = unique_owner()
    doc = new_document()
    engine = admin_engine(migrated_url)

    async def add() -> None:
        database = Database(migrated_url)
        try:
            async with database.session_for(owner, Role.USER) as session:
                await SqlDocumentRepository(session).add(owner, doc)
        finally:
            await database.dispose()

    run_async(add)
    seed_chunk(engine, doc.id, owner, ordinal=0)
    seed_chunk(engine, doc.id, owner, ordinal=1)
    assert count(engine, "chunks", "document_id = :d", d=doc.id) == 2

    async def delete() -> tuple[bool, bool]:
        database = Database(migrated_url)
        try:
            async with database.session_for(owner, Role.USER) as session:
                first = await SqlDocumentRepository(session).delete(owner, doc.id)
            async with database.session_for(owner, Role.USER) as session:
                second = await SqlDocumentRepository(session).delete(owner, doc.id)
            return first, second
        finally:
            await database.dispose()

    assert run_async(delete) == (True, False)
    assert count(engine, "documents", "id = :d", d=doc.id) == 0
    assert count(engine, "chunks", "document_id = :d", d=doc.id) == 0  # cascade, under RLS


def test_a_failed_transaction_leaves_nothing_behind(migrated_url: str) -> None:
    owner = unique_owner()
    doc = new_document()

    async def scenario() -> None:
        database = Database(migrated_url)
        try:
            with pytest.raises(RuntimeError):
                async with database.session_for(owner, Role.USER) as session:
                    await SqlDocumentRepository(session).add(owner, doc)
                    raise RuntimeError("boom")
        finally:
            await database.dispose()

    run_async(scenario)
    assert count(admin_engine(migrated_url), "documents", "id = :d", d=doc.id) == 0


def test_an_invalid_owner_id_is_refused_before_touching_the_database(migrated_url: str) -> None:
    async def scenario() -> None:
        database = Database(migrated_url)
        try:
            with pytest.raises(ValueError, match="invalid owner id"):
                async with database.session_for("x'; DROP TABLE documents;--", Role.USER):
                    pass  # pragma: no cover
        finally:
            await database.dispose()

    run_async(scenario)
