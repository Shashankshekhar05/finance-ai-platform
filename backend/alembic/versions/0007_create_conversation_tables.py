"""Create conversation history tables: conversations, conversation_messages.

Revision ID: 0007_create_conversation_tables
Revises: 0006_create_document_chunks

- conversations: one thread per (company, owner). Company FK RESTRICT
  (tenant with history cannot vanish); user FK CASCADE. Title optional.
- conversation_messages: append-only log. Explicit per-conversation
  `sequence` with UNIQUE(conversation_id, sequence) for deterministic
  ordering; conversation FK CASCADE (thread delete removes messages and
  nothing else); company FK RESTRICT; role VARCHAR+CHECK (user|assistant)
  so no system/token/secret content type can exist at the DB layer.
- Additive only: no existing table touched.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_create_conversation_tables"
down_revision: Union[str, Sequence[str], None] = "0006_create_document_chunks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(200), nullable=True),
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
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_conversations_company_id", "conversations", ["company_id"])
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])
    op.create_index(
        "ix_conversations_company_user",
        "conversations",
        ["company_id", "user_id"],
    )

    op.create_table(
        "conversation_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("role IN ('user', 'assistant')", name="ck_messages_role"),
        sa.CheckConstraint(
            "char_length(content) > 0", name="ck_messages_content_nonempty"
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "conversation_id", "sequence", name="uq_messages_conversation_sequence"
        ),
    )
    op.create_index(
        "ix_conversation_messages_conversation_id",
        "conversation_messages",
        ["conversation_id"],
    )
    op.create_index(
        "ix_conversation_messages_company_id", "conversation_messages", ["company_id"]
    )
    op.create_index(
        "ix_messages_conversation",
        "conversation_messages",
        ["conversation_id", "sequence"],
    )


def downgrade() -> None:
    for index in (
        "ix_conversation_messages_conversation_id",
        "ix_conversation_messages_company_id",
        "ix_messages_conversation",
    ):
        op.drop_index(index, table_name="conversation_messages")
    op.drop_table("conversation_messages")
    for index in (
        "ix_conversations_company_id",
        "ix_conversations_user_id",
        "ix_conversations_company_user",
    ):
        op.drop_index(index, table_name="conversations")
    op.drop_table("conversations")
