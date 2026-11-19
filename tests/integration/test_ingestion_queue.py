# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""The worker queue against a real PostgreSQL: claim, SKIP LOCKED, stale reclaim, complete,
fail, release, and the worker role's privileges (TDD 4.9, ADR-010)."""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from sqlalchemy import Engine, Row, text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from eka.adapters.db.engine import Database
from eka.adapters.db.ingestion_queue import SqlIngestionQueue
from eka.domain.models import Chunk, ClaimedDocument, NewChunk
from tests.fakes import FakeEmbedder
from tests.integration.helpers import admin_engine, count, run_async, seed_document, unique_owner

EMBEDDER = FakeEmbedder()
T = TypeVar("T")


def new_chunks(n: int, document_text: str = "Leave policy text") -> list[NewChunk]:
    chunks = [
        Chunk(
            ordinal=i,
            text=f"{document_text} part {i}",
            locator={"type": "page", "page": i + 1},
            char_start=0,
            char_end=10,
            token_count=5,
        )
        for i in range(n)
    ]
    vectors = EMBEDDER.embed_documents([c.text for c in chunks])
    return [NewChunk(chunk, vector) for chunk, vector in zip(chunks, vectors, strict=True)]


def with_queue(url: str, scenario: Callable[[SqlIngestionQueue, Database], Awaitable[T]]) -> T:
    async def runner() -> T:
        database = Database(url)
        try:
            return await scenario(SqlIngestionQueue(database), database)
        finally:
            await database.dispose()

    return run_async(runner)


def status_of(engine: Engine, document_id: uuid.UUID) -> Row[Any]:
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT status, error_code, attempts, locked_at FROM documents WHERE id = :id"),
            {"id": document_id},
        ).one()


def test_claim_takes_the_oldest_pending_document_and_marks_it_processing(
    isolated_url: str,
) -> None:
    engine = admin_engine(isolated_url)
    first = seed_document(engine, unique_owner(), "first.pdf")
    second = seed_document(engine, unique_owner(), "second.pdf")

    async def scenario(queue: SqlIngestionQueue, _: Database) -> list[ClaimedDocument | None]:
        return [await queue.claim(stale_minutes=10, max_attempts=3) for _ in range(3)]

    got = with_queue(isolated_url, scenario)
    assert got[0] is not None and got[0].id == first and got[0].attempts == 1
    assert got[1] is not None and got[1].id == second
    assert got[2] is None  # nothing left
    row = status_of(engine, first)
    assert row.status == "processing" and row.locked_at is not None and row.attempts == 1
    assert got[0].filename == "first.pdf" and got[0].storage_key.endswith(str(first))


def test_concurrent_workers_never_claim_the_same_document(isolated_url: str) -> None:
    engine = admin_engine(isolated_url)
    ids = {seed_document(engine, unique_owner()) for _ in range(6)}

    async def scenario(queue: SqlIngestionQueue, _: Database) -> list[ClaimedDocument | None]:
        return await asyncio.gather(
            *(queue.claim(stale_minutes=10, max_attempts=3) for _ in range(6))
        )

    claimed = [c.id for c in with_queue(isolated_url, scenario) if c is not None]
    assert len(claimed) == len(set(claimed)) == 6  # six workers, six different documents
    assert set(claimed) == ids


def test_with_one_document_and_many_workers_exactly_one_wins(isolated_url: str) -> None:
    engine = admin_engine(isolated_url)
    seed_document(engine, unique_owner())

    async def scenario(queue: SqlIngestionQueue, _: Database) -> list[ClaimedDocument | None]:
        return await asyncio.gather(
            *(queue.claim(stale_minutes=10, max_attempts=3) for _ in range(5))
        )

    results = with_queue(isolated_url, scenario)
    assert len([r for r in results if r is not None]) == 1


def test_a_stale_claim_is_taken_over_but_a_fresh_one_is_left_alone(isolated_url: str) -> None:
    engine = admin_engine(isolated_url)
    stale = seed_document(engine, unique_owner(), "stale.pdf")
    fresh = seed_document(engine, unique_owner(), "fresh.pdf")
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE documents SET status='processing', attempts=1, "
                "locked_at = now() - interval '1 hour' WHERE id = :id"
            ),
            {"id": stale},
        )
        connection.execute(
            text(
                "UPDATE documents SET status='processing', attempts=1, "
                "locked_at = now() - interval '1 minute' WHERE id = :id"
            ),
            {"id": fresh},
        )

    async def scenario(queue: SqlIngestionQueue, _: Database) -> list[ClaimedDocument | None]:
        return [await queue.claim(stale_minutes=10, max_attempts=3) for _ in range(2)]

    got = with_queue(isolated_url, scenario)
    assert got[0] is not None and got[0].id == stale and got[0].attempts == 2
    assert got[1] is None  # the fresh claim belongs to a live worker


def test_a_stale_claim_that_used_all_its_attempts_is_failed_not_retried(isolated_url: str) -> None:
    engine = admin_engine(isolated_url)
    document = seed_document(engine, unique_owner())
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE documents SET status='processing', attempts=3, "
                "locked_at = now() - interval '1 hour' WHERE id = :id"
            ),
            {"id": document},
        )

    async def scenario(queue: SqlIngestionQueue, _: Database) -> ClaimedDocument | None:
        return await queue.claim(stale_minutes=10, max_attempts=3)

    assert with_queue(isolated_url, scenario) is None
    row = status_of(engine, document)
    assert row.status == "failed" and row.error_code == "max_attempts"


def test_complete_stores_chunks_with_vectors_and_marks_the_document_ready(
    isolated_url: str,
) -> None:
    engine = admin_engine(isolated_url)
    owner = unique_owner()
    document = seed_document(engine, owner)

    async def scenario(queue: SqlIngestionQueue, _: Database) -> bool:
        claimed = await queue.claim(stale_minutes=10, max_attempts=3)
        assert claimed is not None
        return await queue.complete(
            document,
            new_chunks(4),
            page_count=4,
            embedding_model="fake-embedder",
            chunk_config="tokens=40;overlap=5;v1",
        )

    assert with_queue(isolated_url, scenario) is True
    row = status_of(engine, document)
    assert row.status == "ready" and row.locked_at is None
    assert count(engine, "chunks", "document_id = :d", d=document) == 4
    with engine.connect() as connection:
        info = connection.execute(
            text(
                "SELECT owner_id, embedding_model, chunk_config, tsv IS NOT NULL AS has_tsv, "
                "vector_dims(embedding) AS dims, locator->>'page' AS page "
                "FROM chunks WHERE document_id = :d AND ordinal = 2"
            ),
            {"d": document},
        ).one()
        counts = connection.execute(
            text("SELECT page_count, chunk_count FROM documents WHERE id = :d"), {"d": document}
        ).one()
    assert info.owner_id == owner  # copied from the document, never from the caller
    assert (info.embedding_model, info.chunk_config) == ("fake-embedder", "tokens=40;overlap=5;v1")
    assert info.has_tsv and info.dims == 384 and info.page == "3"
    assert (counts.page_count, counts.chunk_count) == (4, 4)


def test_reprocessing_replaces_the_chunks_instead_of_adding_to_them(isolated_url: str) -> None:
    engine = admin_engine(isolated_url)
    document = seed_document(engine, unique_owner())

    async def scenario(queue: SqlIngestionQueue, _: Database) -> list[bool]:
        results: list[bool] = []
        for number_of_chunks in (5, 2):
            await queue.claim(stale_minutes=10, max_attempts=3)
            results.append(
                await queue.complete(
                    document,
                    new_chunks(number_of_chunks),
                    page_count=None,
                    embedding_model="m",
                    chunk_config="c",
                )
            )
            with engine.begin() as connection:  # put it back in the queue, as a re-run would
                connection.execute(
                    text("UPDATE documents SET status='pending' WHERE id = :id"), {"id": document}
                )
        return results

    assert with_queue(isolated_url, scenario) == [True, True]
    assert count(engine, "chunks", "document_id = :d", d=document) == 2


def test_complete_for_a_deleted_document_stores_nothing(isolated_url: str) -> None:
    engine = admin_engine(isolated_url)
    document = seed_document(engine, unique_owner())

    async def scenario(queue: SqlIngestionQueue, _: Database) -> bool:
        await queue.claim(stale_minutes=10, max_attempts=3)
        with engine.begin() as connection:  # the owner deletes it while the worker works
            connection.execute(text("DELETE FROM documents WHERE id = :id"), {"id": document})
        return await queue.complete(
            document, new_chunks(3), page_count=None, embedding_model="m", chunk_config="c"
        )

    assert with_queue(isolated_url, scenario) is False
    assert count(engine, "chunks", "document_id = :d", d=document) == 0


def test_fail_and_release_only_touch_a_document_being_processed(isolated_url: str) -> None:
    engine = admin_engine(isolated_url)
    pending = seed_document(engine, unique_owner())
    working = seed_document(engine, unique_owner())
    exhausted = seed_document(engine, unique_owner())
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE documents SET status='processing', attempts=1 WHERE id = :id"),
            {"id": working},
        )
        connection.execute(
            text("UPDATE documents SET status='processing', attempts=3 WHERE id = :id"),
            {"id": exhausted},
        )

    async def scenario(queue: SqlIngestionQueue, _: Database) -> None:
        await queue.fail(pending, "corrupt")  # not processing: ignored
        await queue.release(working, max_attempts=3)  # attempts left: back to pending
        await queue.release(exhausted, max_attempts=3)  # none left: failed
        await queue.fail(working, "corrupt")  # pending again, so ignored

    with_queue(isolated_url, scenario)
    assert status_of(engine, pending).status == "pending"
    assert status_of(engine, working).status == "pending"
    after = status_of(engine, exhausted)
    assert after.status == "failed" and after.error_code == "max_attempts"


def test_a_permanent_failure_records_its_code_and_clears_the_claim(isolated_url: str) -> None:
    engine = admin_engine(isolated_url)
    document = seed_document(engine, unique_owner())

    async def scenario(queue: SqlIngestionQueue, _: Database) -> None:
        await queue.claim(stale_minutes=10, max_attempts=3)
        await queue.fail(document, "encrypted")

    with_queue(isolated_url, scenario)
    row = status_of(engine, document)
    assert (row.status, row.error_code, row.locked_at) == ("failed", "encrypted", None)


def test_the_worker_role_has_only_the_privileges_it_needs(isolated_url: str) -> None:
    engine = admin_engine(isolated_url)
    document = seed_document(engine, unique_owner())

    async def attempt(sql: str) -> BaseException | None:
        database = Database(isolated_url)
        try:
            async with database.worker_session() as session:
                await session.execute(text(sql), {"id": document})
            return None
        except (ProgrammingError, DBAPIError) as error:
            return error
        finally:
            await database.dispose()

    denied = run_async(lambda: attempt("DELETE FROM documents WHERE id = :id"))
    assert denied is not None and "permission denied" in str(denied)
    denied = run_async(lambda: attempt("INSERT INTO documents (owner_id) VALUES ('x')"))
    assert denied is not None
    allowed = run_async(lambda: attempt("UPDATE documents SET attempts = attempts WHERE id = :id"))
    assert allowed is None
