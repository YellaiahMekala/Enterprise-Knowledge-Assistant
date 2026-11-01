"""Alembic environment. Migrations run synchronously over psycopg 3 (ADR-020).

The URL comes from ``sqlalchemy.url`` if a caller set it (tests do), otherwise from the
``EKA_DATABASE_URL`` environment variable. Migrations need a role that can create roles and
extensions; the API itself never connects with that power.
"""

import os
from logging.config import fileConfig

from alembic import context
from dotenv import dotenv_values
from sqlalchemy import create_engine, pool

from eka.adapters.db.tables import metadata

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def _database_url() -> str:
    """Precedence: a URL set by the caller, then the real environment, then the local .env file
    (the same sources the application reads, so the documented quick start works)."""
    url = (
        config.get_main_option("sqlalchemy.url")
        or os.environ.get("EKA_DATABASE_URL")
        or dotenv_values(".env").get("EKA_DATABASE_URL")
    )
    if not url:
        raise RuntimeError(
            "Set EKA_DATABASE_URL (postgresql+psycopg://...) in the environment or .env "
            "to run migrations."
        )
    return url


def run_migrations_online() -> None:
    engine = create_engine(_database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("Offline (SQL-script) mode is not supported; the migration creates roles.")
run_migrations_online()
