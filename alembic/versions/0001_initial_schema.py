"""Initial schema: pgvector, documents, chunks, indexes, roles and row-level security.

Revision ID: 0001
Revises:
Create Date: 2026-10-31

Written as SQL on purpose: the generated tsvector column, the HNSW index, the roles and the
policies are what TDD section 5 specifies, and autogenerate cannot express all of them.

Roles are created NOLOGIN. They carry privileges, not credentials: the application connects as
its own login role and the API drops to ``eka_api`` per transaction (see ``adapters/db/engine.py``).
No password appears in a migration.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Same rule as eka.domain.models.USER_ID_PATTERN, enforced again by the database.
_OWNER_CHECK = "owner_id ~ '^[A-Za-z0-9_.-]{1,36}$'"
# NULL when the setting is absent, so the comparison is NULL and no row matches: fail closed.
_SESSION_OWNER = "current_setting('app.owner_id', true)"


def _create_role(name: str) -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{name}') THEN
                CREATE ROLE {name} NOLOGIN;
            END IF;
        END
        $$
        """
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    _create_role("eka_api")
    _create_role("eka_worker")

    op.execute(
        f"""
        CREATE TABLE documents (
            id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            owner_id      text        NOT NULL,
            filename      text        NOT NULL,
            content_type  text        NOT NULL,
            size_bytes    bigint      NOT NULL,
            sha256        text        NOT NULL,
            storage_key   text        NOT NULL,
            status        text        NOT NULL DEFAULT 'pending',
            error_code    text,
            attempts      integer     NOT NULL DEFAULT 0,
            page_count    integer,
            chunk_count   integer,
            locked_at     timestamptz,
            created_at    timestamptz NOT NULL DEFAULT now(),
            updated_at    timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT documents_owner_sha256_key UNIQUE (owner_id, sha256),
            CONSTRAINT documents_status_check
                CHECK (status IN ('pending', 'processing', 'ready', 'failed')),
            CONSTRAINT documents_owner_check CHECK ({_OWNER_CHECK}),
            CONSTRAINT documents_size_check CHECK (size_bytes >= 0),
            CONSTRAINT documents_attempts_check CHECK (attempts >= 0)
        )
        """
    )
    op.execute("CREATE INDEX documents_owner_created ON documents (owner_id, created_at DESC)")
    op.execute(
        "CREATE INDEX documents_queue ON documents (created_at) "
        "WHERE status IN ('pending', 'processing')"
    )

    op.execute(
        f"""
        CREATE TABLE chunks (
            id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            document_id      uuid    NOT NULL,
            owner_id         text    NOT NULL,
            ordinal          integer NOT NULL,
            text             text    NOT NULL,
            locator          jsonb   NOT NULL,
            char_start       integer NOT NULL,
            char_end         integer NOT NULL,
            token_count      integer NOT NULL,
            embedding        vector(384) NOT NULL,
            embedding_model  text    NOT NULL,
            chunk_config     text    NOT NULL,
            tsv              tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED,
            CONSTRAINT chunks_document_id_fkey
                FOREIGN KEY (document_id) REFERENCES documents (id) ON DELETE CASCADE,
            CONSTRAINT chunks_document_ordinal_key UNIQUE (document_id, ordinal),
            CONSTRAINT chunks_owner_check CHECK ({_OWNER_CHECK}),
            CONSTRAINT chunks_span_check CHECK (char_end >= char_start)
        )
        """
    )
    op.execute("CREATE INDEX chunks_owner ON chunks (owner_id)")
    # Starting values (m, ef_construction); tuned from measurements in phase P3.
    op.execute(
        "CREATE INDEX chunks_embedding_hnsw ON chunks "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )
    op.execute("CREATE INDEX chunks_tsv_gin ON chunks USING gin (tsv)")

    # Row-level security. FORCE applies the policies to the table owner as well.
    for table in ("documents", "chunks"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    op.execute(
        f"""
        CREATE POLICY documents_owner ON documents FOR ALL TO eka_api
            USING (owner_id = {_SESSION_OWNER})
            WITH CHECK (owner_id = {_SESSION_OWNER})
        """
    )
    # Admins see document metadata across users (the table holds no text), read-only.
    op.execute(
        """
        CREATE POLICY documents_admin_read ON documents FOR SELECT TO eka_api
            USING (current_setting('app.role', true) = 'admin')
        """
    )
    # Admins get no policy on chunks: they cannot read passages.
    op.execute(
        f"""
        CREATE POLICY chunks_owner ON chunks FOR SELECT TO eka_api
            USING (owner_id = {_SESSION_OWNER})
        """
    )
    # The ingestion worker (phase P2) works across owners, limited by grants to these two tables.
    op.execute(
        "CREATE POLICY documents_worker ON documents FOR ALL TO eka_worker "
        "USING (true) WITH CHECK (true)"
    )
    op.execute(
        "CREATE POLICY chunks_worker ON chunks FOR ALL TO eka_worker USING (true) WITH CHECK (true)"
    )

    # Least privilege. The API never writes chunks; chunks of a deleted document go by cascade.
    op.execute("GRANT USAGE ON SCHEMA public TO eka_api, eka_worker")
    op.execute("GRANT SELECT, INSERT, DELETE ON documents TO eka_api")
    op.execute("GRANT SELECT ON chunks TO eka_api")
    op.execute("GRANT SELECT, UPDATE ON documents TO eka_worker")
    op.execute("GRANT SELECT, INSERT, DELETE ON chunks TO eka_worker")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS chunks")
    op.execute("DROP TABLE IF EXISTS documents")
    # Roles are cluster-wide; leave them if another database still depends on them.
    for name in ("eka_api", "eka_worker"):
        op.execute(
            f"""
            DO $$
            BEGIN
                DROP ROLE IF EXISTS {name};
            EXCEPTION WHEN dependent_objects_still_exist THEN
                NULL;
            END
            $$
            """
        )
