"""Engine and the per-request, row-level-security-scoped session.

Isolation has two layers (ADR-012). The repositories always filter by ``owner_id``; this module
supplies the second layer. Each session opens a transaction, drops to the non-owner role
``eka_api`` (``SET LOCAL ROLE``), and sets ``app.owner_id`` / ``app.role`` for the policies. If the
setting is missing the policies match nothing, so a bug fails closed.

``SET LOCAL ROLE`` makes the guarantee independent of how the login role was created: even a
superuser connection (the local Compose database) runs queries as ``eka_api`` and cannot bypass
the policies. Deployed environments should still connect as a non-superuser member of ``eka_api``.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from eka.domain.models import Role, is_valid_user_id

API_ROLE = "eka_api"  # constant, so interpolating it into SET ROLE is safe
WORKER_ROLE = "eka_worker"  # the ingestion worker: cross-owner, grants limited to two tables
CONNECT_TIMEOUT_S = 5


class Database:
    def __init__(self, url: str) -> None:
        # Engine creation does not connect; the first query does.
        self._engine: AsyncEngine = create_async_engine(
            url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=5,
            connect_args={"connect_timeout": CONNECT_TIMEOUT_S},
        )
        self._sessions = async_sessionmaker(self._engine, expire_on_commit=False)

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    async def ping(self) -> None:
        """Raises if the database cannot be reached."""
        async with self._engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    @asynccontextmanager
    async def session_for(self, owner_id: str, role: Role) -> AsyncIterator[AsyncSession]:
        """One transaction scoped to ``owner_id``; commits on success, rolls back on error."""
        if not is_valid_user_id(owner_id):
            raise ValueError("invalid owner id")
        async with self._sessions() as session, session.begin():
            await session.execute(text(f"SET LOCAL ROLE {API_ROLE}"))
            await session.execute(
                text(
                    "SELECT set_config('app.owner_id', :owner, true), "
                    "set_config('app.role', :role, true)"
                ),
                {"owner": owner_id, "role": role.value},
            )
            yield session

    @asynccontextmanager
    async def worker_session(self) -> AsyncIterator[AsyncSession]:
        """One transaction as the ingestion worker role. Used only by the worker process (it
        serves every owner); the policies for this role are explicit in migration 0001."""
        async with self._sessions() as session, session.begin():
            await session.execute(text(f"SET LOCAL ROLE {WORKER_ROLE}"))
            yield session

    async def dispose(self) -> None:
        await self._engine.dispose()
