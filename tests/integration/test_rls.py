# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""Row-level security (ADR-012, Test Strategy 3.4): the second isolation layer, tested as the API
role on a real database. Seeding uses the superuser, which bypasses RLS by design; every
assertion goes through the ``eka_api`` / ``eka_worker`` roles."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.ext.asyncio import create_async_engine

from eka.adapters.db.engine import Database
from eka.adapters.db.repositories import SqlDocumentRepository
from eka.domain.models import Role
from tests.integration.helpers import (
    admin_engine,
    count,
    new_document,
    run_async,
    seed_chunk,
    seed_document,
    unique_owner,
)

pytestmark = pytest.mark.integration


def _two_owners_with_data(url: str) -> tuple[str, str, uuid.UUID, uuid.UUID]:
    engine = admin_engine(url)
    alice, bob = unique_owner("alice"), unique_owner("bob")
    doc_a, doc_b = seed_document(engine, alice), seed_document(engine, bob)
    seed_chunk(engine, doc_a, alice)
    seed_chunk(engine, doc_b, bob)
    return alice, bob, doc_a, doc_b


def test_a_user_sees_only_their_own_documents_and_chunks(migrated_url: str) -> None:
    alice, bob, doc_a, doc_b = _two_owners_with_data(migrated_url)

    async def scenario() -> tuple[set[uuid.UUID], set[str]]:
        database = Database(migrated_url)
        try:
            async with database.session_for(bob, Role.USER) as session:
                docs = (await session.execute(text("SELECT id FROM documents"))).scalars().all()
                owners = (
                    (await session.execute(text("SELECT owner_id FROM chunks"))).scalars().all()
                )
            return set(docs), set(owners)
        finally:
            await database.dispose()

    doc_ids, chunk_owners = run_async(scenario)
    assert doc_b in doc_ids
    assert doc_a not in doc_ids
    assert chunk_owners == {bob}  # bob's chunks only; alice's are invisible


def test_without_the_session_setting_no_rows_are_visible(migrated_url: str) -> None:
    """Fail closed: a code path that forgets to set the owner sees nothing, not everything."""
    _two_owners_with_data(migrated_url)

    async def scenario() -> tuple[int, int]:
        engine = create_async_engine(migrated_url)
        try:
            async with engine.begin() as connection:
                await connection.execute(text("SET LOCAL ROLE eka_api"))
                documents = (
                    await connection.execute(text("SELECT count(*) FROM documents"))
                ).scalar_one()
                chunks = (
                    await connection.execute(text("SELECT count(*) FROM chunks"))
                ).scalar_one()
            return int(documents), int(chunks)
        finally:
            await engine.dispose()

    assert run_async(scenario) == (0, 0)


def test_a_reused_connection_does_not_keep_the_previous_owner(migrated_url: str) -> None:
    """set_config(..., true) is transaction-local. On a pool of one connection, a later
    transaction that sets nothing must not inherit the earlier owner."""
    alice, *_ = _two_owners_with_data(migrated_url)

    async def scenario() -> tuple[int, int]:
        engine = create_async_engine(migrated_url, pool_size=1, max_overflow=0)
        try:
            async with engine.begin() as connection:
                await connection.execute(text("SET LOCAL ROLE eka_api"))
                await connection.execute(
                    text("SELECT set_config('app.owner_id', :o, true)"), {"o": alice}
                )
                first = (
                    await connection.execute(text("SELECT count(*) FROM documents"))
                ).scalar_one()
            async with engine.begin() as connection:  # same physical connection, new transaction
                await connection.execute(text("SET LOCAL ROLE eka_api"))
                second = (
                    await connection.execute(text("SELECT count(*) FROM documents"))
                ).scalar_one()
            return int(first), int(second)
        finally:
            await engine.dispose()

    first, second = run_async(scenario)
    assert first >= 1
    assert second == 0


def test_rls_still_isolates_when_the_owner_argument_is_forged(migrated_url: str) -> None:
    """Layer two on its own: even if application code passed the wrong owner_id to a repository,
    the session's policy hides the other user's rows."""
    alice, bob, doc_a, _ = _two_owners_with_data(migrated_url)

    async def scenario() -> tuple[object, int]:
        database = Database(migrated_url)
        try:
            async with database.session_for(bob, Role.USER) as session:
                # Layer one is deliberately wrong here: asking as alice inside bob's session.
                forged = await SqlDocumentRepository(session).get(alice, doc_a)
                visible = (
                    await session.execute(
                        text("SELECT count(*) FROM documents WHERE id = :d"), {"d": doc_a}
                    )
                ).scalar_one()
            return forged, int(visible)
        finally:
            await database.dispose()

    forged, visible = run_async(scenario)
    assert forged is None
    assert visible == 0


def test_inserting_a_row_for_another_owner_is_rejected(migrated_url: str) -> None:
    alice, bob = unique_owner("alice"), unique_owner("bob")

    async def scenario() -> None:
        database = Database(migrated_url)
        try:
            async with database.session_for(bob, Role.USER) as session:
                await SqlDocumentRepository(session).add(alice, new_document())
        finally:
            await database.dispose()

    with pytest.raises(DBAPIError, match="row-level security"):
        run_async(scenario)
    assert count(admin_engine(migrated_url), "documents", "owner_id = :o", o=alice) == 0


def test_a_user_cannot_delete_another_users_document(migrated_url: str) -> None:
    alice, bob, doc_a, _ = _two_owners_with_data(migrated_url)

    async def scenario() -> int:
        database = Database(migrated_url)
        try:
            async with database.session_for(bob, Role.USER) as session:
                result = await session.execute(
                    text("DELETE FROM documents WHERE id = :d"), {"d": doc_a}
                )
                return int(result.rowcount)  # type: ignore[attr-defined]
        finally:
            await database.dispose()

    assert run_async(scenario) == 0
    assert count(admin_engine(migrated_url), "documents", "id = :d", d=doc_a) == 1


def test_an_admin_reads_document_metadata_across_users_but_never_chunks(migrated_url: str) -> None:
    alice, bob, doc_a, doc_b = _two_owners_with_data(migrated_url)
    admin = unique_owner("admin")

    async def scenario() -> tuple[set[uuid.UUID], int, int, int]:
        database = Database(migrated_url)
        try:
            async with database.session_for(admin, Role.ADMIN) as session:
                docs = set(
                    (await session.execute(text("SELECT id FROM documents"))).scalars().all()
                )
                chunks = (await session.execute(text("SELECT count(*) FROM chunks"))).scalar_one()
                deleted = (
                    await session.execute(text("DELETE FROM documents WHERE id = :d"), {"d": doc_a})
                ).rowcount  # type: ignore[attr-defined]
                updated_or_inserted = 0
            return docs, int(chunks), int(deleted), updated_or_inserted
        finally:
            await database.dispose()

    docs, chunks, deleted, _ = run_async(scenario)
    assert {doc_a, doc_b} <= docs  # metadata of other users is visible to an admin
    assert chunks == 0  # but no passages
    assert deleted == 0  # and the admin policy is read-only
    assert count(admin_engine(migrated_url), "documents", "id = :d", d=doc_a) == 1


def test_a_normal_user_does_not_get_admin_visibility(migrated_url: str) -> None:
    """Role is a per-session setting from the credential; a user session never sees other users."""
    alice, bob, doc_a, _ = _two_owners_with_data(migrated_url)

    async def scenario() -> int:
        database = Database(migrated_url)
        try:
            async with database.session_for(bob, Role.USER) as session:
                return int(
                    (
                        await session.execute(
                            text("SELECT count(*) FROM documents WHERE id = :d"), {"d": doc_a}
                        )
                    ).scalar_one()
                )
        finally:
            await database.dispose()

    assert run_async(scenario) == 0


def test_the_api_role_cannot_write_chunks(migrated_url: str) -> None:
    alice, _, doc_a, _ = _two_owners_with_data(migrated_url)

    async def scenario() -> None:
        database = Database(migrated_url)
        try:
            async with database.session_for(alice, Role.USER) as session:
                await session.execute(text("DELETE FROM chunks"))
        finally:
            await database.dispose()

    with pytest.raises(ProgrammingError, match="permission denied"):
        run_async(scenario)


def test_the_worker_role_works_across_owners_on_documents_and_chunks_only(
    migrated_url: str,
) -> None:
    alice, bob, doc_a, doc_b = _two_owners_with_data(migrated_url)

    async def scenario() -> tuple[set[uuid.UUID], str]:
        engine = create_async_engine(migrated_url)
        try:
            async with engine.begin() as connection:
                await connection.execute(text("SET LOCAL ROLE eka_worker"))
                docs = set(
                    (await connection.execute(text("SELECT id FROM documents"))).scalars().all()
                )
            denied = ""
            try:
                async with engine.begin() as connection:
                    await connection.execute(text("SET LOCAL ROLE eka_worker"))
                    await connection.execute(
                        text(
                            "INSERT INTO documents (owner_id, filename, content_type, size_bytes, "
                            "sha256, storage_key) VALUES ('w', 'f', 't', 1, 's', 'k')"
                        )
                    )
            except ProgrammingError as error:
                denied = str(error.orig)
            return docs, denied
        finally:
            await engine.dispose()

    docs, denied = run_async(scenario)
    assert {doc_a, doc_b} <= docs  # the worker is not scoped to one owner
    assert "permission denied" in denied  # but it cannot create documents


def test_the_database_rejects_a_malformed_owner_id(migrated_url: str) -> None:
    engine = admin_engine(migrated_url)
    with pytest.raises(DBAPIError, match="documents_owner_check"), engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO documents (owner_id, filename, content_type, size_bytes, sha256, "
                "storage_key) VALUES ('bad owner!', 'f', 't', 1, 's', 'k')"
            )
        )
    with pytest.raises(DBAPIError, match="documents_owner_check"), engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO documents (owner_id, filename, content_type, size_bytes, sha256, "
                "storage_key) VALUES ('', 'f', 't', 1, 's', 'k')"
            )
        )
