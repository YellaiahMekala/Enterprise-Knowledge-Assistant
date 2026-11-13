"""Link following for the web fallback (ADR-039): which links, robots.txt, caps and freshness."""

import dataclasses
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest

from eka.domain.errors import WebFetchRefused
from eka.domain.models import Document, DocumentStatus, Role, WebPage
from eka.ingestion.html_text import link_scope, page_links
from eka.services.documents import DocumentService, UploadPolicy
from eka.services.web_fallback import WebFallback, WebSettings, page_filename
from tests.fakes import InMemoryDocumentRepository, InMemoryFileStore

ENTRY = "https://docs.example.org/3/tutorial/index.html"
NOW = datetime(2026, 11, 14, 9, 0, tzinfo=UTC)
POLICY = UploadPolicy(
    max_upload_bytes=1_000_000, max_documents=20, text_extensions=(".md",), max_text_bytes=50_000
)
INDEX = """<title>Tutorial</title><h1>Tutorial</h1><p>Start here.</p>
<nav><a href="classes.html">Classes</a> <a href="modules.html#packages">Modules</a>
<a href="classes.html#top">Classes again</a> <a href="errors.html">Errors</a>
<a href="../library/os.html">Outside the directory</a>
<a href="https://evil.example.net/x.html">Other host</a>
<a href="http://docs.example.org/3/tutorial/plain.html">Not https</a> <a href="logo.png">Image</a>
<a href="mailto:a@example.org">Mail</a> <a href="index.html">Itself</a></nav>"""


def page(url: str) -> str:
    name = url.rsplit("/", 1)[-1]
    return f"<title>{name}</title><h1>{name}</h1><p>Text of {name}.</p>"


class SiteFetcher:
    """A stand-in site: the index, three linked pages and a configurable robots.txt."""

    def __init__(self, robots: str | None = "", robots_refusal: str = "http_404") -> None:
        self.robots = robots
        self.robots_refusal = robots_refusal
        self.calls: list[str] = []

    async def fetch(self, url: str) -> WebPage:
        self.calls.append(url)
        if url.endswith("/robots.txt"):
            if self.robots is None:
                raise WebFetchRefused(self.robots_refusal)
            return WebPage(url, "text/plain", self.robots)
        if url == ENTRY:
            return WebPage(url, "text/html", INDEX)
        if url.endswith("errors.html"):
            raise WebFetchRefused("http_500")
        return WebPage(url, "text/html", page(url))


class Site:
    def __init__(self, fetcher: SiteFetcher, max_linked_pages: int = 5) -> None:
        self.repo = InMemoryDocumentRepository()
        self.store = InMemoryFileStore()
        self.fetcher = fetcher

        @asynccontextmanager
        async def documents(owner: str, role: Role) -> AsyncGenerator[DocumentService, None]:
            yield DocumentService(self.repo, self.store, POLICY)

        async def sleep(seconds: float) -> None:  # the stand-in worker indexes everything at once
            for doc_id, row in list(self.repo.rows.items()):
                if row.status is DocumentStatus.PENDING:
                    self.repo.rows[doc_id] = dataclasses.replace(row, status=DocumentStatus.READY)

        self.fallback = WebFallback(
            fetcher,
            documents,
            WebSettings(entry_urls=(ENTRY,), max_linked_pages=max_linked_pages, wait_seconds=3),
            now=lambda: NOW,
            clock=lambda: 0.0,
            sleep=sleep,
        )

    async def refresh(self) -> tuple[uuid.UUID, ...]:
        return await self.fallback.refresh("alice", Role.USER)

    def sources(self) -> set[str]:
        return {r.source_url for r in self.repo.rows.values() if r.source_url}


def test_links_stay_in_the_entry_pages_directory_and_appear_once() -> None:
    links = page_links(WebPage(ENTRY, "text/html", INDEX), link_scope(ENTRY))
    assert links == [
        "https://docs.example.org/3/tutorial/classes.html",
        "https://docs.example.org/3/tutorial/modules.html",
        "https://docs.example.org/3/tutorial/errors.html",
    ]
    assert link_scope("https://docs.example.org/3/") == "https://docs.example.org/3/"
    assert page_links(WebPage(ENTRY, "text/plain", INDEX), link_scope(ENTRY)) == []


@pytest.mark.anyio
async def test_linked_pages_are_stored_like_entry_pages_and_a_failed_one_is_skipped() -> None:
    site = Site(SiteFetcher())
    ids = await site.refresh()
    assert site.sources() == {
        ENTRY,
        "https://docs.example.org/3/tutorial/classes.html",
        "https://docs.example.org/3/tutorial/modules.html",
    }
    assert len(ids) == 3
    assert "https://docs.example.org/robots.txt" in site.fetcher.calls
    stored = {r.filename for r in site.repo.rows.values()}
    assert page_filename("https://docs.example.org/3/tutorial/classes.html") in stored


@pytest.mark.anyio
async def test_off_by_default_only_the_entry_page_is_fetched() -> None:
    site = Site(SiteFetcher(), max_linked_pages=0)
    await site.refresh()
    assert site.fetcher.calls == [ENTRY]


@pytest.mark.anyio
async def test_the_cap_counts_links_per_entry_page() -> None:
    site = Site(SiteFetcher(), max_linked_pages=1)
    await site.refresh()
    assert site.sources() == {ENTRY, "https://docs.example.org/3/tutorial/classes.html"}


@pytest.mark.anyio
async def test_robots_txt_disallow_is_respected() -> None:
    robots = "User-agent: *\nDisallow: /3/tutorial/classes.html\n"
    site = Site(SiteFetcher(robots=robots))
    await site.refresh()
    assert "https://docs.example.org/3/tutorial/classes.html" not in site.sources()
    assert "https://docs.example.org/3/tutorial/modules.html" in site.sources()


@pytest.mark.anyio
async def test_a_robots_rule_for_this_agent_blocks_everything() -> None:
    site = Site(SiteFetcher(robots="User-agent: eka-web-fallback\nDisallow: /\n"))
    await site.refresh()
    assert site.sources() == {ENTRY}


@pytest.mark.anyio
async def test_an_unreadable_robots_txt_means_no_links_but_a_missing_one_allows_them() -> None:
    blocked = Site(SiteFetcher(robots=None, robots_refusal="timeout"))
    await blocked.refresh()
    assert blocked.sources() == {ENTRY}

    missing = Site(SiteFetcher(robots=None, robots_refusal="http_404"))
    await missing.refresh()
    assert len(missing.sources()) == 3


@pytest.mark.anyio
async def test_a_fresh_linked_page_is_not_fetched_again() -> None:
    site = Site(SiteFetcher())
    classes = "https://docs.example.org/3/tutorial/classes.html"
    fresh = NOW - timedelta(hours=1)
    document = Document(
        id=uuid.uuid4(),
        owner_id="alice",
        filename=page_filename(classes),
        content_type="text/plain",
        size_bytes=3,
        sha256=uuid.uuid4().hex,
        storage_key="alice/c",
        status=DocumentStatus.READY,
        error_code=None,
        attempts=1,
        page_count=None,
        chunk_count=1,
        created_at=fresh,
        updated_at=fresh,
        source_url=classes,
        fetched_at=fresh,
    )
    site.repo.rows[document.id] = document
    await site.refresh()
    assert classes not in site.fetcher.calls
