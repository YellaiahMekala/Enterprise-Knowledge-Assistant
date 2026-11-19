# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""Optional web fallback (ADR-030, FR-37): pages from an owner-configured allowlist.

Called only when the user's own documents give no or weak evidence. For each configured entry
URL the user has no fresh copy of, the page is fetched through the guarded fetcher, turned into
Markdown and uploaded as a normal document owned by the asking user, with its source URL and
fetch time. The worker chunks and embeds it like any upload (the API role cannot write chunks),
so this waits a bounded time for it to become ready. Older copies of the same page are removed.

A fresh copy is already part of the user's normal search, so it is never fetched again before
``refresh_hours``; a question that its pages cannot answer is refused as before.

Link following (ADR-039, off unless ``max_linked_pages`` > 0): when an entry page is fetched, up
to that many pages it links to are fetched too, one level deep only, and only under the entry
page's own directory on the same host. Each link goes through the same guarded fetcher (allowlist,
public addresses, size and time caps) and must be allowed by the host's robots.txt.
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser
from uuid import UUID

from eka.domain.errors import EkaError, NotFound, WebFetchRefused
from eka.domain.models import Document, DocumentStatus, Role, WebPage
from eka.ingestion.html_text import link_scope, page_links, page_to_markdown
from eka.ports.web import PageFetcher
from eka.services.documents import DocumentService

logger = logging.getLogger(__name__)

DocumentScope = Callable[[str, Role], AbstractAsyncContextManager[DocumentService]]

_HEADER_BYTES = 1024
USER_AGENT = "eka-web-fallback"
# robots.txt answers that mean "no rules": everything may be fetched.
_NO_ROBOTS = {"http_404", "http_410"}


@dataclass(frozen=True, slots=True)
class WebSettings:
    entry_urls: tuple[str, ...]
    refresh_hours: int = 24
    wait_seconds: float = 30.0
    poll_seconds: float = 1.0
    max_text_bytes: int = 512 * 1024
    # Pages linked from each entry page to fetch as well; 0 turns link following off.
    max_linked_pages: int = 0


def page_filename(url: str) -> str:
    parts = urlsplit(url)
    name = f"{parts.hostname}{parts.path}".rstrip("/").replace("/", "_")
    return name[:120] + ".md"


class WebFallback:
    def __init__(
        self,
        fetcher: PageFetcher,
        documents: DocumentScope,
        settings: WebSettings,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._fetcher = fetcher
        self._documents = documents
        self._settings = settings
        self._now = now
        self._clock = clock
        self._sleep = sleep
        # One refresh at a time per user, so two weak questions do not store the page twice.
        self._locks: dict[str, asyncio.Lock] = {}

    async def refresh(self, owner_id: str, role: Role) -> tuple[UUID, ...]:
        """Ids of pages newly fetched and ready to search; empty if nothing new is available."""
        lock = self._locks.setdefault(owner_id, asyncio.Lock())
        async with lock:
            return await self._refresh(owner_id, role)

    async def _refresh(self, owner_id: str, role: Role) -> tuple[UUID, ...]:
        fetched_at = self._now()
        oldest_fresh = fetched_at - timedelta(hours=self._settings.refresh_hours)
        due: list[tuple[str, list[Document]]] = []
        async with self._documents(owner_id, role) as documents:
            for url in self._settings.entry_urls:
                copies = await documents.web_copies(owner_id, url)
                latest = copies[0].fetched_at if copies else None
                if latest is None or latest < oldest_fresh:
                    due.append((url, copies))

        stored: list[tuple[UUID, list[Document]]] = []
        entry_pages: list[tuple[str, WebPage]] = []
        for url, copies in due:
            page = await self._fetch(url)
            if page is None:
                continue
            entry_pages.append((url, page))
            await self._store(owner_id, role, url, page, copies, fetched_at, stored)

        linked = 0
        if self._settings.max_linked_pages > 0:
            linked = await self._follow_links(
                owner_id, role, entry_pages, oldest_fresh, fetched_at, stored
            )

        ready = await self._wait_until_ready(owner_id, role, [doc_id for doc_id, _ in stored])
        async with self._documents(owner_id, role) as documents:
            for document_id, older in stored:
                if document_id in ready:
                    for copy in older:
                        with contextlib.suppress(NotFound):
                            await documents.delete(owner_id, copy.id)
        logger.info("web fallback fetched=%s linked=%s ready=%s", len(stored), linked, len(ready))
        return tuple(ready)

    async def _follow_links(
        self,
        owner_id: str,
        role: Role,
        entry_pages: list[tuple[str, WebPage]],
        oldest_fresh: datetime,
        fetched_at: datetime,
        stored: list[tuple[UUID, list[Document]]],
    ) -> int:
        """Fetch and store the pages the entry pages link to; returns how many were stored."""
        robots: dict[str, RobotFileParser | None] = {}
        seen = set(self._settings.entry_urls)
        due: list[tuple[str, list[Document]]] = []
        for entry_url, page in entry_pages:
            links = [u for u in page_links(page, link_scope(entry_url)) if u not in seen]
            taken = 0
            for url in links:
                if taken >= self._settings.max_linked_pages:
                    break
                seen.add(url)
                if not await self._robots_allow(url, robots):
                    logger.info("web link skipped by robots.txt host=%s", urlsplit(url).hostname)
                    continue
                taken += 1
                async with self._documents(owner_id, role) as documents:
                    copies = await documents.web_copies(owner_id, url)
                if (
                    copies
                    and copies[0].fetched_at is not None
                    and copies[0].fetched_at >= oldest_fresh
                ):
                    continue
                due.append((url, copies))

        # The linked pages are fetched together, so following links costs about one fetch time.
        pages = await asyncio.gather(*(self._fetch(url) for url, _ in due))
        before = len(stored)
        for (url, copies), linked_page in zip(due, pages, strict=True):
            if linked_page is not None:
                await self._store(owner_id, role, url, linked_page, copies, fetched_at, stored)
        return len(stored) - before

    async def _robots_allow(self, url: str, cache: dict[str, RobotFileParser | None]) -> bool:
        """The link host's robots.txt, read once per refresh. Unreadable: do not follow."""
        host = urlsplit(url).netloc
        if host not in cache:
            cache[host] = await self._robots(host)
        rules = cache[host]
        return rules is not None and rules.can_fetch(USER_AGENT, url)

    async def _robots(self, host: str) -> RobotFileParser | None:
        rules = RobotFileParser()
        try:
            page = await self._fetcher.fetch(f"https://{host}/robots.txt")
        except WebFetchRefused as refused:
            if refused.reason not in _NO_ROBOTS:
                logger.warning("robots.txt unreadable host=%s reason=%s", host, refused.reason)
                return None
            rules.parse([])  # no robots.txt: no rules
            return rules
        rules.parse(page.text.splitlines())
        return rules

    async def _fetch(self, url: str) -> WebPage | None:
        try:
            return await self._fetcher.fetch(url)
        except WebFetchRefused as refused:
            logger.warning(
                "web fetch refused host=%s reason=%s", urlsplit(url).hostname, refused.reason
            )
            return None

    async def _store(
        self,
        owner_id: str,
        role: Role,
        url: str,
        page: WebPage,
        copies: list[Document],
        fetched_at: datetime,
        stored: list[tuple[UUID, list[Document]]],
    ) -> None:
        data = self._page_bytes(url, page, fetched_at)
        if data is None:
            return
        try:
            async with self._documents(owner_id, role) as documents:
                document, _created = await documents.upload(
                    owner_id,
                    page_filename(url),
                    "text/plain",
                    data,
                    source_url=url,
                    fetched_at=fetched_at,
                )
        except EkaError as error:  # quota reached, type not allowed, storage down
            logger.warning("web page not stored: %s", type(error).__name__)
            return
        stored.append((document.id, [c for c in copies if c.id != document.id]))

    def _page_bytes(self, url: str, page: WebPage, fetched_at: datetime) -> bytes | None:
        host = urlsplit(url).hostname
        title, text = page_to_markdown(page)
        if not text:
            logger.warning("web page has no text host=%s", host)
            return None
        # The header makes each fetch a distinct document (the store deduplicates identical
        # bytes) and tells the reader where the text came from.
        header = f"# {title or url}\n\nSource: {url}\nFetched: {fetched_at.isoformat()}\n\n"
        body = text.encode("utf-8")[: self._settings.max_text_bytes - _HEADER_BYTES]
        return header.encode("utf-8") + body.decode("utf-8", errors="ignore").encode("utf-8")

    async def _wait_until_ready(
        self, owner_id: str, role: Role, document_ids: list[UUID]
    ) -> list[UUID]:
        waiting = set(document_ids)
        ready: list[UUID] = []
        deadline = self._clock() + self._settings.wait_seconds
        while waiting:
            async with self._documents(owner_id, role) as documents:
                for document_id in list(waiting):
                    try:
                        status = (await documents.get(owner_id, document_id)).status
                    except NotFound:  # the user deleted it meanwhile
                        status = DocumentStatus.FAILED
                    if status is DocumentStatus.READY:
                        ready.append(document_id)
                    if status in (DocumentStatus.READY, DocumentStatus.FAILED):
                        waiting.discard(document_id)
            if not waiting or self._clock() >= deadline:
                break
            await self._sleep(self._settings.poll_seconds)
        if waiting:
            logger.info("web pages still being processed: %s", len(waiting))
        return ready
