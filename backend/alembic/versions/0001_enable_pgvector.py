"""Enable pgvector extension.

Revision ID: 0001_enable_pgvector

Foundation migration: installs the `vector` extension so later phases can
add `vector(768)` columns. No tables are created here (AGENTS.md §11).
Raw SQL is used because extension management is a migration-level operation.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0001_enable_pgvector"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS vector")
