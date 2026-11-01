"""Table definitions (SQLAlchemy Core), mirroring the Alembic migration.

The migration is the source of truth for the schema; these objects exist so repositories write
explicit, typed queries and so a test can detect drift between the two. Dimension 384 matches
BAAI/bge-small-en-v1.5 (ADR-005).
"""

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Column,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR

EMBEDDING_DIM = 384

metadata = MetaData()

documents = Table(
    "documents",
    metadata,
    Column("id", Uuid, primary_key=True, server_default=text("gen_random_uuid()")),
    Column("owner_id", Text, nullable=False),
    Column("filename", Text, nullable=False),
    Column("content_type", Text, nullable=False),
    Column("size_bytes", BigInteger, nullable=False),
    Column("sha256", Text, nullable=False),
    Column("storage_key", Text, nullable=False),
    Column("status", Text, nullable=False, server_default="pending"),
    Column("error_code", Text),
    Column("attempts", Integer, nullable=False, server_default="0"),
    Column("page_count", Integer),
    Column("chunk_count", Integer),
    Column("locked_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("owner_id", "sha256", name="documents_owner_sha256_key"),
)
Index("documents_owner_created", documents.c.owner_id, documents.c.created_at.desc())
Index(
    "documents_queue",
    documents.c.created_at,
    postgresql_where=text("status IN ('pending', 'processing')"),
)

chunks = Table(
    "chunks",
    metadata,
    Column("id", Uuid, primary_key=True, server_default=text("gen_random_uuid()")),
    Column(
        "document_id",
        Uuid,
        ForeignKey("documents.id", ondelete="CASCADE", name="chunks_document_id_fkey"),
        nullable=False,
    ),
    # Denormalised from documents so the owner filter applies in the same scan as the vector search.
    Column("owner_id", Text, nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column("text", Text, nullable=False),
    Column("locator", JSONB, nullable=False),
    Column("char_start", Integer, nullable=False),
    Column("char_end", Integer, nullable=False),
    Column("token_count", Integer, nullable=False),
    Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
    Column("embedding_model", Text, nullable=False),
    Column("chunk_config", Text, nullable=False),
    Column("tsv", TSVECTOR, Computed("to_tsvector('english', text)", persisted=True)),
    UniqueConstraint("document_id", "ordinal", name="chunks_document_ordinal_key"),
)
Index("chunks_owner", chunks.c.owner_id)
Index(
    "chunks_embedding_hnsw",
    chunks.c.embedding,
    postgresql_using="hnsw",
    postgresql_with={"m": 16, "ef_construction": 64},  # starting values; tuned from measurements
    postgresql_ops={"embedding": "vector_cosine_ops"},
)
Index("chunks_tsv_gin", chunks.c.tsv, postgresql_using="gin")
