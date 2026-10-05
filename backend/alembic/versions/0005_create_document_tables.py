"""Create document domain tables: documents, document_pages.

Revision ID: 0005_create_document_tables
Revises: 0004_create_finance_tables

- documents: company-owned (RESTRICT), sha256 dedupe via
  UNIQUE(company_id, sha256_hash), status VARCHAR+CHECK
  (uploaded|processing|indexed|failed — see DATABASE_RULES.md §10 for the
  naming divergence from RAG_RULES pending/ready).
- document_pages: CASCADE on document delete (pages are part of the
  document), RESTRICT company FK, UNIQUE(document_id, page_number),
  1-based page numbers, type/status VARCHAR+CHECKs, JSONB table summaries.
- No document_chunks yet (chunking phase), no vectors here.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_create_document_tables"
down_revision: Union[str, Sequence[str], None] = "0004_create_finance_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _stamp_columns() -> list:
    return [
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
    ]


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("media_type", sa.String(100), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("sha256_hash", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("ingestion_error", sa.String(1000), nullable=True),
        sa.Column("ingestion_error_code", sa.String(64), nullable=True),
        *_stamp_columns(),
        sa.CheckConstraint(
            "status IN ('uploaded', 'processing', 'indexed', 'failed')",
            name="ck_documents_status",
        ),
        sa.CheckConstraint("file_size > 0", name="ck_documents_file_size_positive"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "company_id", "sha256_hash", name="uq_documents_company_sha256"
        ),
    )
    op.create_index("ix_documents_company_id", "documents", ["company_id"])
    op.create_index("ix_documents_sha256_hash", "documents", ["sha256_hash"])
    op.create_index(
        "ix_documents_company_status", "documents", ["company_id", "status"]
    )

    op.create_table(
        "document_pages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("page_type", sa.String(16), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("extraction_status", sa.String(16), nullable=False),
        sa.Column("extraction_error", sa.String(500), nullable=True),
        sa.Column(
            "text_char_count", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "has_tables", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "has_images", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("table_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tables", postgresql.JSONB(), nullable=True),
        *_stamp_columns(),
        sa.CheckConstraint("page_number >= 1", name="ck_pages_number_positive"),
        sa.CheckConstraint(
            "page_type IN ('narrative', 'table', 'visual', 'mixed')",
            name="ck_pages_type",
        ),
        sa.CheckConstraint(
            "extraction_status IN ('ok', 'failed')",
            name="ck_pages_extraction_status",
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "document_id", "page_number", name="uq_pages_document_number"
        ),
    )
    op.create_index("ix_document_pages_document_id", "document_pages", ["document_id"])
    op.create_index("ix_document_pages_company_id", "document_pages", ["company_id"])
    op.create_index(
        "ix_pages_company_document", "document_pages", ["company_id", "document_id"]
    )


def downgrade() -> None:
    for table, indexes in (
        (
            "document_pages",
            [
                "ix_document_pages_document_id",
                "ix_document_pages_company_id",
                "ix_pages_company_document",
            ],
        ),
        (
            "documents",
            [
                "ix_documents_company_id",
                "ix_documents_sha256_hash",
                "ix_documents_company_status",
            ],
        ),
    ):
        for index in indexes:
            op.drop_index(index, table_name=table)
        op.drop_table(table)
