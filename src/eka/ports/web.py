"""Web page port for the optional web fallback (ADR-030)."""

from typing import Protocol

from eka.domain.models import WebPage


class PageFetcher(Protocol):
    async def fetch(self, url: str) -> WebPage:
        """The page at ``url``; raises ``WebFetchRefused`` for anything the policy forbids."""
        ...
