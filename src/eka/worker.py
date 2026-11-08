"""The ingestion worker process. Run with: python -m eka.worker

Like ``main.py`` this is a composition root: it is the other place that chooses adapters. It
loads the embedding model first (so a broken model cache fails the container at start-up, not on
the first document), then processes the queue until it is told to stop.
"""

import asyncio
import contextlib
import logging
import signal
from functools import partial

from eka.adapters.db.engine import Database
from eka.adapters.db.ingestion_queue import SqlIngestionQueue
from eka.adapters.embedder_fastembed import FastEmbedEmbedder
from eka.adapters.storage import build_file_store
from eka.config import Settings
from eka.ingestion.parse_runner import parse_in_child
from eka.logging_config import configure_logging
from eka.services.processing import IngestionProcessor, ProcessingSettings

logger = logging.getLogger(__name__)


async def run_worker(settings: Settings, stop: asyncio.Event) -> None:
    if settings.database_url is None:
        raise RuntimeError("EKA_DATABASE_URL is required to run the worker")
    database = Database(settings.database_url.get_secret_value())
    try:
        logger.info("loading embedding model %s", settings.embedding_model)
        embedder = await asyncio.to_thread(
            FastEmbedEmbedder,
            settings.embedding_model,
            settings.embedding_cache_dir,
            settings.embedding_dim,
        )
        processor = IngestionProcessor(
            SqlIngestionQueue(database),
            build_file_store(settings),
            embedder,
            partial(
                parse_in_child,
                text_extensions=settings.allowed_text_extensions,
                limits=settings.parse_limits,
                timeout_seconds=settings.parse_timeout_seconds,
            ),
            ProcessingSettings(
                chunk_tokens=settings.chunk_tokens,
                chunk_overlap_tokens=settings.chunk_overlap_tokens,
                stale_claim_minutes=settings.worker_stale_claim_minutes,
                max_attempts=settings.worker_max_attempts,
                poll_seconds=settings.worker_poll_seconds,
            ),
        )
        logger.info("worker ready")
        await processor.run(stop)
    finally:
        await database.dispose()
        logger.info("worker stopped")


async def _amain() -> None:
    settings = Settings(component="worker")
    configure_logging(settings.log_level, json_logs=settings.log_json)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for name in ("SIGINT", "SIGTERM"):
        # Windows event loops cannot add signal handlers; Ctrl+C still raises KeyboardInterrupt.
        with contextlib.suppress(NotImplementedError, AttributeError, ValueError):
            loop.add_signal_handler(getattr(signal, name), stop.set)
    await run_worker(settings, stop)


def main() -> None:
    # psycopg's async mode cannot use Windows' default ProactorEventLoop (see runtime.py).
    with (
        contextlib.suppress(KeyboardInterrupt),
        asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner,
    ):
        runner.run(_amain())


if __name__ == "__main__":
    main()
