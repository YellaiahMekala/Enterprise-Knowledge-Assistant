# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""Migrations on a real database: apply, schema checks, downgrade, drift from the table models."""

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from eka.adapters.db.tables import metadata


def _scalar(url: str, sql: str) -> object:
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            return connection.execute(text(sql)).scalar_one()
    finally:
        engine.dispose()


def test_upgrade_creates_the_schema(fresh_alembic: tuple[Config, str]) -> None:
    config, url = fresh_alembic
    command.upgrade(config, "head")
    engine = create_engine(url)
    try:
        inspector = inspect(engine)
        assert {"documents", "chunks", "alembic_version"} <= set(inspector.get_table_names())
        indexes = {i["name"] for t in ("documents", "chunks") for i in inspector.get_indexes(t)}
        assert {
            "documents_owner_created",
            "documents_queue",
            "chunks_owner",
            "chunks_embedding_hnsw",
            "chunks_tsv_gin",
        } <= indexes
    finally:
        engine.dispose()


def test_pgvector_is_at_least_0_8_for_iterative_scan(fresh_alembic: tuple[Config, str]) -> None:
    config, url = fresh_alembic
    command.upgrade(config, "head")
    version = str(_scalar(url, "SELECT extversion FROM pg_extension WHERE extname = 'vector'"))
    parts = tuple(int(p) for p in version.split(".")[:2])
    assert parts >= (0, 8), f"pgvector {version}: iterative scan needs 0.8.0 or later"


def test_embedding_column_is_384_dimensional(fresh_alembic: tuple[Config, str]) -> None:
    config, url = fresh_alembic
    command.upgrade(config, "head")
    column_type = _scalar(
        url,
        "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
        "WHERE attrelid = 'chunks'::regclass AND attname = 'embedding'",
    )
    assert column_type == "vector(384)"


def test_row_level_security_is_enabled_and_forced(fresh_alembic: tuple[Config, str]) -> None:
    config, url = fresh_alembic
    command.upgrade(config, "head")
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE relname IN ('documents', 'chunks') ORDER BY relname"
                )
            ).all()
    finally:
        engine.dispose()
    assert [tuple(r) for r in rows] == [("chunks", True, True), ("documents", True, True)]


def test_table_models_match_the_migrated_schema(fresh_alembic: tuple[Config, str]) -> None:
    """Drift check: the models in tables.py and the migration describe the same schema."""
    config, url = fresh_alembic
    command.upgrade(config, "head")
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection, opts={"compare_type": True})
            diff = compare_metadata(context, metadata)
    finally:
        engine.dispose()
    assert diff == [], f"models and migration disagree: {diff}"


def test_downgrade_removes_the_tables_and_upgrade_can_be_repeated(
    fresh_alembic: tuple[Config, str],
) -> None:
    config, url = fresh_alembic
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    engine = create_engine(url)
    try:
        assert not {"documents", "chunks"} & set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    command.upgrade(config, "head")  # reversible and repeatable
    engine = create_engine(url)
    try:
        assert {"documents", "chunks"} <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_the_drift_check_can_actually_detect_a_difference(
    fresh_alembic: tuple[Config, str],
) -> None:
    """Guards the check above against passing vacuously."""
    from sqlalchemy import Column, Integer, MetaData, Table

    config, url = fresh_alembic
    command.upgrade(config, "head")
    other = MetaData()
    Table("surprise", other, Column("id", Integer, primary_key=True))
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            diff = compare_metadata(MigrationContext.configure(connection), other)
    finally:
        engine.dispose()
    assert any("surprise" in str(item) for item in diff)
