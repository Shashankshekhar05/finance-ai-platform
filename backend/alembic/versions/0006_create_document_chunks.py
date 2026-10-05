"""Create document_chunks + embedding-readiness columns on documents.

Revision ID: 0006_create_document_chunks
Revises: 0005_create_document_tables

- document_chunks: single-page chunks (RAG_RULES §3.1), embedding
  vector(768) NOT NULL via the pgvector SQLAlchemy type, UNIQUE(document_id,
  chunk_index), tenant + doc + provenance indexes, HNSW cosine index.
- documents: embedding_status (pending|indexing|ready|failed) +
  embedding_error + embedding_model + chunk_count. Additive only: existing
  Phase 4 rows keep status/pages untouched; backfill is explicit via the
  index endpoint, never silent.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0006_create_document_chunks"
down_revision: Union[str, Sequence[str], None] = "0005_create_document_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "embedding_status", sa.String(16), nullable=False, server_default="pending"
        ),
    )
    op.add_column(
        "documents", sa.Column("embedding_error", sa.String(1000), nullable=True)
    )
    op.add_column(
        "documents", sa.Column("embedding_model", sa.String(200), nullable=True)
    )
    op.add_column(
        "documents",
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "ck_documents_embedding_status",
        "documents",
        "embedding_status IN ('pending', 'indexing', 'ready', 'failed')",
    )

    op.create_table(
        "document_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_char_count", sa.BigInteger(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("chunk_type", sa.String(16), nullable=False),
        sa.Column("chunk_metadata", postgresql.JSONB(), nullable=True),
        sa.Column("embedding", Vector(768), nullable=False),
        sa.Column("embedding_model", sa.String(200), nullable=False),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("char_length(text) > 0", name="ck_chunks_text_nonempty"),
        sa.CheckConstraint("page_number >= 1", name="ck_chunks_page_positive"),
        sa.CheckConstraint("chunk_index >= 0", name="ck_chunks_index_nonnegative"),
        sa.CheckConstraint("chunk_type IN ('text', 'table')", name="ck_chunks_type"),
        sa.CheckConstraint(
            "embedding_dimensions = 768", name="ck_chunks_dimensions_768"
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["page_id"], ["document_pages.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "document_id", "chunk_index", name="uq_chunks_document_index"
        ),
    )
    op.create_index("ix_document_chunks_company_id", "document_chunks", ["company_id"])
    op.create_index(
        "ix_document_chunks_document_id", "document_chunks", ["document_id"]
    )
    op.create_index("ix_document_chunks_page_id", "document_chunks", ["page_id"])
    op.create_index(
        "ix_chunks_company_document", "document_chunks", ["company_id", "document_id"]
    )
    op.create_index(
        "ix_chunks_company_page", "document_chunks", ["company_id", "page_number"]
    )
    # Cosine-similarity index for retrieval (HNSW, default build params).
    op.create_index(
        "ix_chunks_embedding_hnsw",
        "document_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_chunks_embedding_hnsw", table_name="document_chunks")
    for index in (
        "ix_document_chunks_company_id",
        "ix_document_chunks_document_id",
        "ix_document_chunks_page_id",
        "ix_chunks_company_document",
        "ix_chunks_company_page",
    ):
        op.drop_index(index, table_name="document_chunks")
    op.drop_table("document_chunks")
    op.drop_constraint("ck_documents_embedding_status", "documents", type_="check")
    op.drop_column("documents", "chunk_count")
    op.drop_column("documents", "embedding_model")
    op.drop_column("documents", "embedding_error")
    op.drop_column("documents", "embedding_status")
