"""Run the retrieval evaluation: ingest the corpus as one user, ask every question, score it.

The corpus goes through the same upload service and ingestion processor as a real upload, so the
numbers describe the shipped pipeline. The processor claims pending documents of every owner, so
run this against a dedicated database.
"""

import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from eka.adapters.db.engine import Database
from eka.adapters.db.ingestion_queue import SqlIngestionQueue
from eka.adapters.db.repositories import SqlDocumentRepository
from eka.adapters.db.search import SqlChunkSearch
from eka.adapters.storage_local import LocalFileStore
from eka.domain.models import DocumentStatus, ParseLimits, Role, SearchFilters
from eka.eval.dataset import ChallengeQuestion, Question
from eka.eval.metrics import QuestionResult, first_relevant_rank
from eka.ingestion.parse import parse_document
from eka.ports.embedder import Embedder
from eka.services.documents import DocumentService, UploadPolicy
from eka.services.processing import IngestionProcessor, ProcessingSettings
from eka.services.retrieval import RetrievalService, RetrievalSettings

# The refusal gate looks at the best cosine among this many passages (the API default for top_k).
GATE_TOP_K = 5
TEXT_EXTENSIONS = (".java", ".md", ".txt", ".sql", ".json", ".yml", ".xml", ".properties")


@dataclass(frozen=True, slots=True)
class EvalConfig:
    chunk_tokens: int = 256
    chunk_overlap_tokens: int = 32
    top_k: int = 10
    retrieval: RetrievalSettings = RetrievalSettings()
    any_document: bool = False


@dataclass(frozen=True, slots=True)
class CorpusSummary:
    documents: int
    chunks: int


async def ingest_corpus(
    database: Database, owner: str, corpus_dir: Path, embedder: Embedder, config: EvalConfig
) -> CorpusSummary:
    """Upload every file in ``corpus_dir`` as ``owner`` and process the queue until it is empty.
    Raises if any document does not reach ``ready``."""
    files = sorted(p for p in corpus_dir.iterdir() if p.is_file())
    if not files:
        raise ValueError(f"no files in {corpus_dir}")
    with tempfile.TemporaryDirectory() as work:
        store = LocalFileStore(Path(work))
        policy = UploadPolicy(
            max_upload_bytes=5 * 1024 * 1024,
            max_documents=1000,
            text_extensions=TEXT_EXTENSIONS,
            max_text_bytes=512 * 1024,
        )
        async with database.session_for(owner, Role.USER) as session:
            service = DocumentService(SqlDocumentRepository(session), store, policy)
            for path in files:
                await service.upload(owner, path.name, None, path.read_bytes())

        processor = IngestionProcessor(
            SqlIngestionQueue(database),
            store,
            embedder,
            partial(parse_document, text_extensions=TEXT_EXTENSIONS, limits=ParseLimits()),
            ProcessingSettings(
                chunk_tokens=config.chunk_tokens,
                chunk_overlap_tokens=config.chunk_overlap_tokens,
                stale_claim_minutes=10,
                max_attempts=1,
                poll_seconds=0.1,
            ),
        )
        while await processor.process_one():
            pass

    async with database.session_for(owner, Role.USER) as session:
        documents = await SqlDocumentRepository(session).list_by_owner(owner, limit=1000)
    not_ready = [d.filename for d in documents if d.status is not DocumentStatus.READY]
    if not_ready:
        raise RuntimeError(f"documents that did not reach ready: {not_ready}")
    return CorpusSummary(len(documents), sum(d.chunk_count or 0 for d in documents))


async def delete_corpus(database: Database, owner: str) -> None:
    """Remove the evaluation user's documents (their chunks go with them)."""
    async with database.session_for(owner, Role.USER) as session:
        repository = SqlDocumentRepository(session)
        for document in await repository.list_by_owner(owner, limit=1000):
            await repository.delete(owner, document.id)


async def run_questions(
    database: Database,
    owner: str,
    embedder: Embedder,
    config: EvalConfig,
    questions: Sequence[Question],
) -> list[QuestionResult]:
    results = []
    async with database.session_for(owner, Role.USER) as session:
        service = RetrievalService(SqlChunkSearch(session), embedder, config.retrieval)
        for question in questions:
            hits = await service.search(
                owner, question.question, top_k=config.top_k, filters=SearchFilters()
            )
            results.append(
                QuestionResult(
                    question=question,
                    rank=first_relevant_rank(hits, question, any_document=config.any_document),
                    top_cosine=max((h.cosine for h in hits[:GATE_TOP_K]), default=None),
                    retrieved=tuple(h.filename for h in hits),
                )
            )
    return results


async def challenge_cosines(
    database: Database,
    owner: str,
    embedder: Embedder,
    config: EvalConfig,
    questions: Sequence[ChallengeQuestion],
) -> list[float]:
    """Best-passage cosine for each unanswerable question."""
    values = []
    async with database.session_for(owner, Role.USER) as session:
        service = RetrievalService(SqlChunkSearch(session), embedder, config.retrieval)
        for question in questions:
            hits = await service.search(
                owner, question.question, top_k=GATE_TOP_K, filters=SearchFilters()
            )
            if hits:
                values.append(max(h.cosine for h in hits))
    return values
