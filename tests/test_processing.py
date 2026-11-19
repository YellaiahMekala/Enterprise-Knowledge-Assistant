# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""The worker's processing logic with in-memory doubles: every outcome in TDD 4.9."""

import asyncio
import uuid

import pytest

from eka.domain.models import (
    ClaimedDocument,
    Document,
    DocumentStatus,
    NewDocument,
    ParsedDocument,
    ParseLimits,
)
from eka.ingestion.parse import parse_document
from eka.services.processing import IngestionProcessor, ProcessingSettings
from tests.fakes import FakeEmbedder, InMemoryDocumentRepository, InMemoryFileStore, InMemoryQueue
from tests.files import JAVA_SAMPLE, make_docx, make_encrypted_pdf, make_pdf

SETTINGS = ProcessingSettings(
    chunk_tokens=40,
    chunk_overlap_tokens=5,
    stale_claim_minutes=10,
    max_attempts=3,
    poll_seconds=0.01,
)
LIMITS = ParseLimits(max_pages=50, max_csv_rows=1000, max_text_bytes=100_000)


def parser(filename: str, content_type: str | None, data: bytes) -> ParsedDocument:
    return parse_document(
        filename, content_type, data, text_extensions=(".java", ".txt"), limits=LIMITS
    )


class Harness:
    def __init__(self) -> None:
        self.repository = InMemoryDocumentRepository()
        self.store = InMemoryFileStore()
        self.queue = InMemoryQueue(self.repository)
        self.embedder = FakeEmbedder()
        self.processor = IngestionProcessor(self.queue, self.store, self.embedder, parser, SETTINGS)
        self._counter = 0

    async def add(
        self, name: str, data: bytes, content_type: str, owner: str = "alice"
    ) -> Document:
        self._counter += 1
        document_id = uuid.uuid4()
        key = f"{owner}/{document_id}"
        await self.store.put(key, data, content_type)
        document, _ = await self.repository.add(
            owner,
            NewDocument(
                id=document_id,
                filename=name,
                content_type=content_type,
                size_bytes=len(data),
                sha256=f"{self._counter:064d}",
                storage_key=key,
            ),
        )
        return document

    def row(self, document: Document) -> Document:
        return self.repository.rows[document.id]


@pytest.fixture
def harness() -> Harness:
    return Harness()


@pytest.mark.anyio
async def test_an_empty_queue_does_nothing(harness: Harness) -> None:
    assert await harness.processor.process_one() is False


@pytest.mark.anyio
async def test_a_pdf_becomes_ready_with_embedded_chunks_and_a_page_count(harness: Harness) -> None:
    text = "\n".join(f"Line {i} of the leave policy says something useful." for i in range(30))
    document = await harness.add("p.pdf", make_pdf([text, "Second page text."]), "application/pdf")
    assert await harness.processor.process_one() is True
    row = harness.row(document)
    assert row.status is DocumentStatus.READY
    assert row.page_count == 2 and row.chunk_count and row.chunk_count > 1
    stored = harness.queue.chunks[document.id]
    assert [c.chunk.ordinal for c in stored] == list(range(len(stored)))
    assert {c.chunk.locator["page"] for c in stored} == {1, 2}
    assert all(len(c.embedding) == 384 for c in stored)
    assert all(c.chunk.token_count <= SETTINGS.chunk_tokens for c in stored)


@pytest.mark.anyio
async def test_a_code_file_keeps_line_ranges_that_match_the_source(harness: Harness) -> None:
    document = await harness.add("Greeter.java", JAVA_SAMPLE.encode(), "text/plain")
    await harness.processor.process_one()
    lines = JAVA_SAMPLE.split("\n")
    for item in harness.queue.chunks[document.id]:
        locator = item.chunk.locator
        assert (
            item.chunk.text.rstrip()
            == "\n".join(lines[locator["start"] - 1 : locator["end"]]).rstrip()
        )


@pytest.mark.anyio
async def test_a_docx_keeps_its_section_path(harness: Harness) -> None:
    data = make_docx([("Heading 1", "Leave"), ("Normal", "Five days carry over.")])
    document = await harness.add(
        "a.docx",
        data,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    await harness.processor.process_one()
    assert harness.queue.chunks[document.id][0].chunk.locator["path"] == ["Leave"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("name", "data", "content_type", "code"),
    [
        ("enc.pdf", make_encrypted_pdf(), "application/pdf", "encrypted"),
        ("blank.pdf", make_pdf(["", ""]), "application/pdf", "no_text"),
        ("bad.pdf", b"%PDF-1.4 garbage", "application/pdf", "corrupt"),
        ("latin.txt", "café".encode("latin-1"), "text/plain", "unsupported_encoding"),
    ],
)
async def test_permanent_errors_fail_the_document_once_with_a_fixed_code(
    harness: Harness, name: str, data: bytes, content_type: str, code: str
) -> None:
    document = await harness.add(name, data, content_type)
    await harness.processor.process_one()
    row = harness.row(document)
    assert row.status is DocumentStatus.FAILED and row.error_code == code
    assert harness.queue.released == []  # no retry for a file that can never work
    assert await harness.processor.process_one() is False  # and it is not picked up again


@pytest.mark.anyio
async def test_a_storage_outage_is_retried_then_failed_as_max_attempts(harness: Harness) -> None:
    document = await harness.add("a.pdf", make_pdf(["hello there"]), "application/pdf")
    harness.store.fail_get = True
    for expected_status in (DocumentStatus.PENDING, DocumentStatus.PENDING, DocumentStatus.FAILED):
        await harness.processor.process_one()
        assert harness.row(document).status is expected_status
    assert harness.row(document).error_code == "max_attempts"
    assert harness.row(document).attempts == 3


@pytest.mark.anyio
async def test_a_transient_failure_recovers_when_the_dependency_returns(harness: Harness) -> None:
    document = await harness.add("a.pdf", make_pdf(["hello there"]), "application/pdf")
    harness.store.fail_get = True
    await harness.processor.process_one()
    assert harness.row(document).status is DocumentStatus.PENDING
    harness.store.fail_get = False
    await harness.processor.process_one()
    assert harness.row(document).status is DocumentStatus.READY


@pytest.mark.anyio
async def test_a_result_for_a_deleted_document_is_discarded(harness: Harness) -> None:
    document = await harness.add("a.pdf", make_pdf(["hello there"]), "application/pdf")
    harness.queue.complete_returns = False  # the row vanished while we worked
    assert await harness.processor.process_one() is True
    assert document.id not in harness.queue.chunks


@pytest.mark.anyio
async def test_documents_are_taken_oldest_first_and_each_exactly_once(harness: Harness) -> None:
    first = await harness.add("1.pdf", make_pdf(["one one"]), "application/pdf")
    second = await harness.add("2.pdf", make_pdf(["two two"]), "application/pdf", owner="bob")
    await harness.processor.process_one()
    assert harness.row(first).status is DocumentStatus.READY
    assert harness.row(second).status is DocumentStatus.PENDING
    await harness.processor.process_one()
    assert harness.row(second).status is DocumentStatus.READY
    assert await harness.processor.process_one() is False


@pytest.mark.anyio
async def test_the_run_loop_works_through_the_queue_and_stops_on_request(harness: Harness) -> None:
    documents = [
        await harness.add(f"{i}.pdf", make_pdf([f"text {i}"]), "application/pdf") for i in range(3)
    ]
    stop = asyncio.Event()
    task = asyncio.create_task(harness.processor.run(stop))
    for _ in range(200):
        if all(harness.row(d).status is DocumentStatus.READY for d in documents):
            break
        await asyncio.sleep(0.01)
    stop.set()
    await asyncio.wait_for(task, timeout=5)
    assert all(harness.row(d).status is DocumentStatus.READY for d in documents)


@pytest.mark.anyio
async def test_the_loop_survives_an_exception_from_the_queue(harness: Harness) -> None:
    calls = 0
    original = harness.queue.claim

    async def flaky(**kwargs: int) -> ClaimedDocument | None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionError("database down")
        return await original(**kwargs)

    harness.queue.claim = flaky  # type: ignore[method-assign]
    document = await harness.add("a.pdf", make_pdf(["hello there"]), "application/pdf")
    stop = asyncio.Event()
    task = asyncio.create_task(harness.processor.run(stop))
    for _ in range(300):
        if harness.row(document).status is DocumentStatus.READY:
            break
        await asyncio.sleep(0.01)
    stop.set()
    await asyncio.wait_for(task, timeout=5)
    assert harness.row(document).status is DocumentStatus.READY
