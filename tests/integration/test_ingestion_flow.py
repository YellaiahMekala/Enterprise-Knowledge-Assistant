"""End to end through the real API, real PostgreSQL (row-level security on), real local file
store and the real worker logic; only the embedding model is faked (FakeEmbedder).

Upload -> pending -> worker -> ready with chunks -> isolation -> delete removes rows and file.
"""

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import text

from eka.adapters.db.engine import Database
from eka.adapters.db.ingestion_queue import SqlIngestionQueue
from eka.adapters.storage_local import LocalFileStore
from eka.domain.models import ParsedDocument, ParseLimits
from eka.ingestion.parse import parse_document
from eka.main import create_app
from eka.services.processing import IngestionProcessor, ProcessingSettings
from tests.fakes import FakeEmbedder
from tests.files import JAVA_SAMPLE, make_docx, make_pdf
from tests.helpers import ADMIN_KEY, USER_ID, USER_KEY, make_settings
from tests.integration.helpers import admin_engine, count, run_async

_SELECTOR = {"loop_factory": asyncio.SelectorEventLoop}
USER = {"X-API-Key": USER_KEY}
OTHER = {"X-API-Key": ADMIN_KEY}
EXTENSIONS = (".java", ".md", ".txt")


def process_all(url: str, files: Path) -> int:
    """Run the worker logic until the queue is empty; returns how many documents it took."""

    def parser(name: str, content_type: str | None, data: bytes) -> ParsedDocument:
        return parse_document(
            name, content_type, data, text_extensions=EXTENSIONS, limits=ParseLimits()
        )

    async def scenario() -> int:
        database = Database(url)
        try:
            processor = IngestionProcessor(
                SqlIngestionQueue(database),
                LocalFileStore(files),
                FakeEmbedder(),
                parser,
                ProcessingSettings(
                    chunk_tokens=60,
                    chunk_overlap_tokens=8,
                    stale_claim_minutes=10,
                    max_attempts=3,
                    poll_seconds=0.01,
                ),
            )
            taken = 0
            while await processor.process_one():
                taken += 1
            return taken
        finally:
            await database.dispose()

    return run_async(scenario)


def test_upload_ingest_isolate_and_delete(isolated_url: str, tmp_path: Path) -> None:
    files = tmp_path / "files"
    app = create_app(make_settings(database_url=isolated_url, storage_local_dir=files))
    long_page = "\n".join(f"Policy line {i}: staff may carry over five days." for i in range(40))
    uploads = {
        "policy.pdf": (
            make_pdf([long_page, "Travel is booked through the portal."]),
            "application/pdf",
        ),
        "rules.docx": (
            make_docx([("Heading 1", "Leave"), ("Normal", "Five days carry over.")]),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        "grades.csv": (b"grade,days\nJunior,20\nSenior,25\n", "text/csv"),
        "Greeter.java": (JAVA_SAMPLE.encode(), "text/x-java-source"),
        "broken.pdf": (b"%PDF-1.4 not really a pdf", "application/pdf"),
    }

    with TestClient(app, backend_options=_SELECTOR, raise_server_exceptions=False) as client:
        ids = {}
        for name, (data, content_type) in uploads.items():
            response = client.post(
                "/api/v1/documents", headers=USER, files={"file": (name, data, content_type)}
            )
            assert response.status_code == 202, (name, response.text)
            ids[name] = response.json()["id"]
        duplicate = client.post(
            "/api/v1/documents",
            headers=USER,
            files={"file": ("again.pdf", uploads["policy.pdf"][0], "application/pdf")},
        )
        assert duplicate.status_code == 200 and duplicate.json()["id"] == ids["policy.pdf"]

        assert process_all(isolated_url, files) == len(uploads)

        statuses = {
            name: client.get(f"/api/v1/documents/{document_id}", headers=USER).json()
            for name, document_id in ids.items()
        }
        for name in ("policy.pdf", "rules.docx", "grades.csv", "Greeter.java"):
            assert statuses[name]["status"] == "ready", (name, statuses[name])
            assert statuses[name]["chunk_count"] >= 1
        assert statuses["policy.pdf"]["page_count"] == 2
        assert statuses["broken.pdf"]["status"] == "failed"
        assert statuses["broken.pdf"]["error_code"] == "corrupt"

        # The other user sees nothing of it, through the real row-level-security session.
        assert client.get("/api/v1/documents", headers=OTHER).json()["items"] == []
        assert (
            client.get(f"/api/v1/documents/{ids['policy.pdf']}", headers=OTHER).status_code == 404
        )
        assert (
            client.delete(f"/api/v1/documents/{ids['policy.pdf']}", headers=OTHER).status_code
            == 404
        )

        engine = admin_engine(isolated_url)
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT d.filename, c.owner_id, c.locator, c.embedding_model, c.chunk_config "
                    "FROM chunks c JOIN documents d ON d.id = c.document_id "
                    "ORDER BY d.filename, c.ordinal"
                )
            ).all()
        assert {row.owner_id for row in rows} == {USER_ID}
        locators: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            locator = row.locator if isinstance(row.locator, dict) else json.loads(row.locator)
            locators.setdefault(row.filename, []).append(locator)
        assert {loc["page"] for loc in locators["policy.pdf"]} == {1, 2}
        assert locators["rules.docx"][0]["path"] == ["Leave"]
        assert locators["grades.csv"][0] == {"type": "rows", "start": 1, "end": 2}
        assert all(
            loc["type"] == "lines" and loc["path"] == "Greeter.java"
            for loc in locators["Greeter.java"]
        )
        assert {row.embedding_model for row in rows} == {"fake-embedder"}
        assert {row.chunk_config for row in rows} == {"tokens=60;overlap=8;v1"}

        # Delete removes the document, its chunks (cascade) and the stored file.
        policy_id = ids["policy.pdf"]
        before = count(engine, "chunks", "document_id = :d", d=policy_id)
        assert before > 1
        assert any(files.rglob(policy_id))
        assert client.delete(f"/api/v1/documents/{policy_id}", headers=USER).status_code == 204
        assert count(engine, "chunks", "document_id = :d", d=policy_id) == 0
        assert count(engine, "documents", "id = :d", d=policy_id) == 0
        assert not any(files.rglob(policy_id))
        assert client.get(f"/api/v1/documents/{policy_id}", headers=USER).status_code == 404
