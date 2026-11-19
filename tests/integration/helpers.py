# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""Helpers for the integration tests."""

import asyncio
import json
import uuid
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any, TypeVar

from alembic.config import Config
from sqlalchemy import Engine, create_engine, text

from eka.domain.models import NewDocument

ROOT = Path(__file__).resolve().parents[2]
# Must equal the db image in docker-compose.yml (tests/test_compose.py checks that).
PGVECTOR_IMAGE = "pgvector/pgvector:0.8.7-pg17"

T = TypeVar("T")


def alembic_config(url: str) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def run_async(fn: Callable[[], Coroutine[Any, Any, T]]) -> T:
    """Run a coroutine on a selector event loop: psycopg's async mode cannot use the Windows
    default ProactorEventLoop."""
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        return runner.run(fn())


def unique_owner(prefix: str = "u") -> str:
    """A fresh owner id per test so tests share a database without cleaning up after each other."""
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def new_document(name: str = "a.pdf", sha: str | None = None) -> NewDocument:
    document_id = uuid.uuid4()
    return NewDocument(
        id=document_id,
        filename=name,
        content_type="application/pdf",
        size_bytes=123,
        sha256=sha or uuid.uuid4().hex * 2,
        storage_key=f"owner/{document_id}",
    )


# --- seeding as the superuser (bypasses row-level security by design; used only to arrange) ---


def admin_engine(url: str) -> Engine:
    return create_engine(url)


def seed_document(engine: Engine, owner_id: str, name: str = "seed.pdf") -> uuid.UUID:
    document_id = uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO documents (id, owner_id, filename, content_type, size_bytes, "
                "sha256, storage_key) VALUES (:id, :owner, :name, 'application/pdf', 1, :sha, :key)"
            ),
            {
                "id": document_id,
                "owner": owner_id,
                "name": name,
                "sha": uuid.uuid4().hex * 2,
                "key": f"{owner_id}/{document_id}",
            },
        )
    return document_id


def seed_chunk(
    engine: Engine, document_id: uuid.UUID, owner_id: str, ordinal: int = 0, body: str = "passage"
) -> uuid.UUID:
    chunk_id = uuid.uuid4()
    embedding = json.dumps([0.01] * 384)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO chunks (id, document_id, owner_id, ordinal, text, locator, "
                "char_start, char_end, token_count, embedding, embedding_model, chunk_config) "
                "VALUES (:id, :doc, :owner, :ordinal, :body, CAST(:locator AS jsonb), 0, 1, 1, "
                "CAST(:embedding AS vector), 'test-model', 'test-config')"
            ),
            {
                "id": chunk_id,
                "doc": document_id,
                "owner": owner_id,
                "ordinal": ordinal,
                "body": body,
                "locator": json.dumps({"type": "page", "page": 1}),
                "embedding": embedding,
            },
        )
    return chunk_id


def count(engine: Engine, table: str, where: str = "true", **params: Any) -> int:
    with engine.connect() as connection:
        value = connection.execute(text(f"SELECT count(*) FROM {table} WHERE {where}"), params)
        return int(value.scalar_one())
