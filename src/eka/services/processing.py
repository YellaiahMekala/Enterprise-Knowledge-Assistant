# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""The worker's processing logic: claim a document, read, parse, chunk, embed, store (TDD 4.9).

Outcomes for one document:

* success: chunks and ``ready`` in one transaction;
* permanent error (corrupt, encrypted, no text, too large, bad encoding): ``failed`` with a
  fixed code, never retried;
* transient error (storage or database trouble, a model hiccup): back to ``pending`` until the
  attempt budget is used up, then ``failed`` with ``max_attempts``;
* the document deleted while we worked: our result is discarded.

Parsing and embedding are CPU-bound and run in threads so the event loop stays responsive.
Logs carry ids and counts, never file names or text.
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from eka.domain.errors import PermanentIngestionError
from eka.domain.models import ClaimedDocument, NewChunk, ParsedDocument
from eka.ingestion.chunking import chunk_config_label, chunk_document
from eka.ports.embedder import Embedder
from eka.ports.ingestion_queue import IngestionQueue
from eka.ports.storage import FileStore

logger = logging.getLogger(__name__)

# (filename, declared content type, bytes) -> parsed document. The worker passes a child-process
# parser with a timeout; tests pass an in-process one.
Parser = Callable[[str, str | None, bytes], ParsedDocument]

_EMBED_BATCH = 32


@dataclass(frozen=True, slots=True)
class ProcessingSettings:
    chunk_tokens: int
    chunk_overlap_tokens: int
    stale_claim_minutes: int
    max_attempts: int
    poll_seconds: float


class IngestionProcessor:
    def __init__(
        self,
        queue: IngestionQueue,
        store: FileStore,
        embedder: Embedder,
        parser: Parser,
        settings: ProcessingSettings,
    ) -> None:
        self._queue = queue
        self._store = store
        self._embedder = embedder
        self._parser = parser
        self._settings = settings

    async def process_one(self) -> bool:
        """Claim and process at most one document. ``False`` means the queue was empty."""
        claimed = await self._queue.claim(
            stale_minutes=self._settings.stale_claim_minutes,
            max_attempts=self._settings.max_attempts,
        )
        if claimed is None:
            return False
        started = time.perf_counter()
        try:
            stored = await self._ingest(claimed)
        except PermanentIngestionError as error:
            await self._queue.fail(claimed.id, error.code)
            logger.info("ingestion failed id=%s code=%s", claimed.id, error.code)
        except Exception:
            logger.warning(
                "ingestion error id=%s attempt=%s", claimed.id, claimed.attempts, exc_info=True
            )
            await self._release(claimed)
        else:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            logger.info(
                "ingestion %s id=%s chunks=%s ms=%s",
                "ready" if stored else "discarded (document deleted)",
                claimed.id,
                stored,
                elapsed_ms,
            )
        return True

    async def run(self, stop: asyncio.Event) -> None:
        """Process documents until ``stop`` is set; sleep when the queue is empty."""
        while not stop.is_set():
            try:
                worked = await self.process_one()
            except Exception:  # e.g. the database is down: wait and try again
                logger.warning("worker iteration failed", exc_info=True)
                worked = False
            if not worked:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=self._settings.poll_seconds)

    async def _ingest(self, claimed: ClaimedDocument) -> int:
        """Returns the number of chunks stored, or 0 if the document disappeared meanwhile."""
        data = await self._store.get(claimed.storage_key)
        parsed = await asyncio.to_thread(self._parser, claimed.filename, claimed.content_type, data)
        chunks = await asyncio.to_thread(
            chunk_document,
            parsed.segments,
            self._embedder.count_tokens,
            max_tokens=self._settings.chunk_tokens,
            overlap_tokens=self._settings.chunk_overlap_tokens,
        )
        vectors: list[list[float]] = []
        for start in range(0, len(chunks), _EMBED_BATCH):
            batch = [chunk.text for chunk in chunks[start : start + _EMBED_BATCH]]
            vectors.extend(await asyncio.to_thread(self._embedder.embed_documents, batch))
        stored = await self._queue.complete(
            claimed.id,
            [NewChunk(chunk, vector) for chunk, vector in zip(chunks, vectors, strict=True)],
            page_count=parsed.page_count,
            embedding_model=self._embedder.model_name,
            chunk_config=chunk_config_label(
                self._settings.chunk_tokens, self._settings.chunk_overlap_tokens
            ),
        )
        return len(chunks) if stored else 0

    async def _release(self, claimed: ClaimedDocument) -> None:
        try:
            await self._queue.release(claimed.id, max_attempts=self._settings.max_attempts)
        except Exception:
            # The database may be the reason we are here. The claim goes stale and is retaken.
            logger.warning("could not release id=%s", claimed.id, exc_info=True)
