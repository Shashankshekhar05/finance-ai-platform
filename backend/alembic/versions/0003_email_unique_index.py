"""Unify email uniqueness into a single unique index.

Revision ID: 0003_email_unique_index
Revises: 0002_create_identity_tables

0002 created a UNIQUE constraint plus a separate plain index on
users.email. The ORM models a single unique index for the same guarantee
(race-safe, one backing index). This revision converges the database to
the model so `alembic check` is drift-free. Non-destructive: no data moves.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0003_email_unique_index"
down_revision: Union[str, Sequence[str], None] = "0002_create_identity_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("uq_users_email", "users", type_="unique")
    op.drop_index("ix_users_email", table_name="users")
    op.create_index("ix_users_email", "users", ["email"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_email", table_name="users")
    op.create_index("ix_users_email", "users", ["email"], unique=False)
    op.create_unique_constraint("uq_users_email", "users", ["email"])
