# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""The web fallback service (ADR-030) and its use by answering, with in-memory ports."""

import dataclasses
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest

from eka.domain.answering import REASON_WEAK_EVIDENCE
from eka.domain.errors import WebFetchRefused
from eka.domain.models import Document, DocumentStatus, Role, WebPage
from eka.services.answering import AnswerScope, AnswerService, AnswerSettings, collect_final
from eka.services.documents import DocumentService, UploadPolicy
from eka.services.retrieval import RetrievalService, RetrievalSettings
from eka.services.web_fallback import WebFallback, WebSettings, page_filename
from tests.fakes import (
    FakeEmbedder,
    InMemoryChunkSearch,
    InMemoryConversationRepository,
    InMemoryDocumentRepository,
    InMemoryFileStore,
    ScriptedChatModel,
)

URL = "https://docs.example.org/tutorial/classes.html"
NOW = datetime(2026, 11, 11, 9, 0, tzinfo=UTC)
HTML = "<title>Classes</title><h1>Classes</h1><p>A class bundles data and methods.</p>"
POLICY = UploadPolicy(
    max_upload_bytes=1_000_000, max_documents=5, text_extensions=(".md",), max_text_bytes=50_000
)


class FakeFetcher:
    def __init__(self, html: str = HTML, refuse: str | None = None) -> None:
        self.html = html
        self.refuse = refuse
        self.calls: list[str] = []

    async def fetch(self, url: str) -> WebPage:
        self.calls.append(url)
        if self.refuse:
            raise WebFetchRefused(self.refuse)
        return WebPage(url, "text/html", self.html)


class Setup:
    """A document store plus a stand-in worker: pending documents become ready once the
    fallback has slept ``ready_after`` times (``None``: never)."""

    def __init__(
        self, fetcher: FakeFetcher, *, ready_after: int | None = 1, wait: float = 3
    ) -> None:
        self.repo = InMemoryDocumentRepository()
        self.store = InMemoryFileStore()
        self.fetcher = fetcher
        self.sleeps = 0

        @asynccontextmanager
        async def documents(owner: str, role: Role) -> AsyncGenerator[DocumentService, None]:
            yield DocumentService(self.repo, self.store, POLICY)

        async def sleep(seconds: float) -> None:
            self.sleeps += 1
            if ready_after is not None and self.sleeps >= ready_after:
                for doc_id, row in list(self.repo.rows.items()):
                    if row.status is DocumentStatus.PENDING:
                        self.repo.rows[doc_id] = dataclasses.replace(
                            row, status=DocumentStatus.READY
                        )

        self.fallback = WebFallback(
            fetcher,
            documents,
            WebSettings(entry_urls=(URL,), wait_seconds=wait, poll_seconds=1.0),
            now=lambda: NOW,
            clock=lambda: float(self.sleeps),
            sleep=sleep,
        )

    async def refresh(self, owner: str = "alice") -> tuple[uuid.UUID, ...]:
        return await self.fallback.refresh(owner, Role.USER)

    def web_rows(self) -> list[Document]:
        return [r for r in self.repo.rows.values() if r.source_url == URL]


def stored_copy(
    setup: Setup, fetched_at: datetime, owner: str = "alice", source_url: str | None = URL
) -> Document:
    document = Document(
        id=uuid.uuid4(),
        owner_id=owner,
        filename=page_filename(URL),
        content_type="text/markdown",
        size_bytes=10,
        sha256=uuid.uuid4().hex,
        storage_key=f"{owner}/old",
        status=DocumentStatus.READY,
        error_code=None,
        attempts=1,
        page_count=None,
        chunk_count=1,
        created_at=fetched_at,
        updated_at=fetched_at,
        source_url=source_url,
        fetched_at=fetched_at if source_url else None,
    )
    setup.repo.rows[document.id] = document
    setup.store.objects[document.storage_key] = b"old"
    return document


@pytest.mark.anyio
async def test_a_page_is_stored_as_the_users_markdown_document_with_its_source() -> None:
    setup = Setup(FakeFetcher())
    ids = await setup.refresh()
    (row,) = setup.web_rows()
    assert ids == (row.id,)
    assert row.owner_id == "alice" and row.filename == "docs.example.org_tutorial_classes.html.md"
    assert row.content_type == "text/plain" and row.fetched_at == NOW
    text = setup.store.objects[row.storage_key].decode()
    assert text.startswith(f"# Classes\n\nSource: {URL}\nFetched: 2026-11-11T09:00:00+00:00\n")
    assert "A class bundles data and methods." in text and "<p>" not in text


@pytest.mark.anyio
async def test_a_fresh_copy_is_not_fetched_again() -> None:
    setup = Setup(FakeFetcher())
    stored_copy(setup, NOW - timedelta(hours=23))
    assert await setup.refresh() == ()
    assert setup.fetcher.calls == []


@pytest.mark.anyio
async def test_another_users_copy_does_not_count() -> None:
    setup = Setup(FakeFetcher())
    stored_copy(setup, NOW - timedelta(hours=1), owner="bob")
    assert len(await setup.refresh("alice")) == 1
    assert setup.fetcher.calls == [URL]


@pytest.mark.anyio
async def test_a_stale_copy_is_replaced_once_the_new_one_is_ready() -> None:
    setup = Setup(FakeFetcher())
    old = stored_copy(setup, NOW - timedelta(hours=25))
    (new_id,) = await setup.refresh()
    assert [r.id for r in setup.web_rows()] == [new_id]
    assert old.storage_key not in setup.store.objects


@pytest.mark.anyio
async def test_a_refused_fetch_stores_nothing() -> None:
    setup = Setup(FakeFetcher(refuse="private_address"))
    assert await setup.refresh() == ()
    assert setup.repo.rows == {}


@pytest.mark.anyio
async def test_a_page_without_text_stores_nothing() -> None:
    setup = Setup(FakeFetcher(html="<script>x()</script><nav>menu</nav>"))
    assert await setup.refresh() == ()
    assert setup.repo.rows == {}


@pytest.mark.anyio
async def test_it_waits_for_the_worker_then_returns_the_ready_page() -> None:
    setup = Setup(FakeFetcher(), ready_after=2)
    ids = await setup.refresh()
    assert len(ids) == 1 and setup.sleeps == 2


@pytest.mark.anyio
async def test_a_page_not_ready_in_time_is_kept_for_later_and_not_returned() -> None:
    setup = Setup(FakeFetcher(), ready_after=None, wait=3)
    old = stored_copy(setup, NOW - timedelta(days=2))
    assert await setup.refresh() == ()
    rows = setup.web_rows()
    assert len(rows) == 2 and old in rows  # the old copy stays until the new one is ready


@pytest.mark.anyio
async def test_a_full_quota_skips_the_page() -> None:
    setup = Setup(FakeFetcher())
    for _ in range(POLICY.max_documents):
        stored_copy(setup, NOW, source_url=None)
    assert await setup.refresh() == ()
    assert setup.web_rows() == []


def test_page_filename() -> None:
    assert page_filename("https://docs.example.org/") == "docs.example.org.md"
    assert page_filename("https://a.org/x/y.html?q=1") == "a.org_x_y.html.md"


# --- answering with the fallback ----------------------------------------------------------------

EMBED = FakeEmbedder()
LEAVE = "Staff may carry over five unused leave days into the next year."
CLASSES = "A class bundles data and methods into one unit."


class StubFallback:
    """Stands in for WebFallback: on refresh, a web page appears in the user's search."""

    def __init__(self, search: InMemoryChunkSearch, *, page: str | None = CLASSES) -> None:
        self.search = search
        self.page = page
        self.calls = 0

    async def refresh(self, owner_id: str, role: Role) -> tuple[uuid.UUID, ...]:
        self.calls += 1
        if self.page is None:
            return ()
        document_id = uuid.uuid4()
        self.search.add_document(
            owner_id, document_id, page_filename(URL), source_url=URL, created_at=NOW
        )
        self.search.add_chunk(owner_id, document_id, self.page, EMBED.embed_query(self.page))
        return (document_id,)


def answer_service(model: ScriptedChatModel, page: str | None = CLASSES):  # type: ignore[no-untyped-def]
    search = InMemoryChunkSearch()
    leave = uuid.uuid4()
    search.add_document("alice", leave, "leave.md")
    search.add_chunk("alice", leave, LEAVE, EMBED.embed_query(LEAVE))
    web = StubFallback(search, page=page)

    @asynccontextmanager
    async def scope(owner: str, role: Role) -> AsyncGenerator[AnswerScope, None]:
        yield AnswerScope(
            conversations=InMemoryConversationRepository(),
            retrieval=lambda embedder: RetrievalService(
                search, embedder, RetrievalSettings(candidates=10)
            ),
        )

    async def embedder() -> FakeEmbedder:
        return EMBED

    service = AnswerService(
        scope,
        model,
        embedder,
        AnswerSettings(min_cosine=0.6),
        web=web,  # type: ignore[arg-type]
    )
    return service, web


@pytest.mark.anyio
async def test_weak_evidence_uses_the_web_page_and_cites_it_as_web() -> None:
    model = ScriptedChatModel(["A class bundles data and methods [1]."])
    service, web = answer_service(model)
    done = await collect_final(service.ask("alice", Role.USER, CLASSES))
    assert web.calls == 1 and done["web_fallback"] is True and not done["refused"]
    (citation,) = done["citations"]
    assert citation["kind"] == "web" and citation["source_url"] == URL
    assert citation["fetched_at"] == NOW.isoformat()
    sent = model.stream_calls[0][-1].content
    assert f'source="{URL}"' in sent and 'origin="web page"' in sent
    assert LEAVE not in sent  # only the fetched pages are searched in the second round


@pytest.mark.anyio
async def test_strong_evidence_never_touches_the_web() -> None:
    model = ScriptedChatModel(["Five days carry over [1]."])
    service, web = answer_service(model)
    done = await collect_final(service.ask("alice", Role.USER, LEAVE))
    assert web.calls == 0 and done["web_fallback"] is False
    assert done["citations"][0]["kind"] == "document"
    assert done["citations"][0]["source_url"] is None


@pytest.mark.anyio
async def test_nothing_new_from_the_web_still_refuses() -> None:
    model = ScriptedChatModel(["unused"])
    service, web = answer_service(model, page=None)
    done = await collect_final(service.ask("alice", Role.USER, "how do classes work"))
    assert web.calls == 1 and done["refused"] and done["refusal_reason"] == REASON_WEAK_EVIDENCE
    assert done["web_fallback"] is False and model.stream_calls == []


@pytest.mark.anyio
async def test_a_web_page_that_does_not_match_is_refused_too() -> None:
    model = ScriptedChatModel(["unused"])
    service, web = answer_service(model, page="Opening hours of the museum shop.")
    done = await collect_final(service.ask("alice", Role.USER, "how do classes work"))
    assert web.calls == 1 and done["refused"] and done["refusal_reason"] == REASON_WEAK_EVIDENCE
    assert done["web_fallback"] is True and model.stream_calls == []
