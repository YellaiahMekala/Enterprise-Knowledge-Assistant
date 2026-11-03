"""Fixtures for tests that need a real PostgreSQL with pgvector (Testcontainers).

Skipped with a clear reason when Docker is not available; always run in CI.
"""

import secrets
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url

from tests.integration.helpers import PGVECTOR_IMAGE, alembic_config


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "integration" in str(item.fspath).replace("\\", "/"):
            item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session")
def server_url() -> Iterator[URL]:
    """A throwaway PostgreSQL (the same pgvector image as Compose), superuser connection."""
    try:
        import docker

        docker.from_env().ping()
    except Exception as error:  # Docker missing or its engine stopped
        pytest.skip(f"Docker is not available: {type(error).__name__}")

    from testcontainers.community.postgres import PostgresContainer

    password = secrets.token_hex(8)  # ephemeral container, random per run
    with PostgresContainer(
        PGVECTOR_IMAGE, username="eka", password=password, dbname="postgres", driver="psycopg"
    ) as container:
        yield make_url(container.get_connection_url())


def create_database(server: URL, name: str) -> str:
    """Create an empty database on the server and return its URL (as a string)."""
    engine = create_engine(server, isolation_level="AUTOCOMMIT")
    with engine.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    engine.dispose()
    return server.set(database=name).render_as_string(hide_password=False)


@pytest.fixture(scope="session")
def migrated_url(server_url: URL) -> str:
    """A database with every migration applied, shared by the read/write tests."""
    url = create_database(server_url, "eka_main")
    command.upgrade(alembic_config(url), "head")
    return url


@pytest.fixture
def fresh_alembic(server_url: URL) -> Iterator[tuple[Config, str]]:
    """An empty database plus its Alembic config, for tests that run migrations themselves."""
    name = "eka_mig_" + secrets.token_hex(4)
    url = create_database(server_url, name)
    yield alembic_config(url), url


@pytest.fixture
def isolated_url(server_url: URL) -> str:
    """A private, fully migrated database for one test. Needed where a test claims work from the
    shared queue (it would otherwise pick up documents that other tests left pending)."""
    url = create_database(server_url, "eka_it_" + secrets.token_hex(4))
    command.upgrade(alembic_config(url), "head")
    return url
