"""Create finance domain tables: revenue, expenses, transactions, financial_metrics.

Revision ID: 0004_create_finance_tables
Revises: 0003_email_unique_index

All four are company-owned (company_id FK → companies.id ON DELETE RESTRICT:
money rows are never cascade-deleted). Amounts are NUMERIC(18,2) CHECK > 0
(metrics NUMERIC(24,8) for ratios); no FLOAT anywhere. Type/role-like fields
are VARCHAR + CHECK, no Postgres ENUM types. source_document_id has NO FK:
the documents table does not exist yet (added in the documents phase).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_create_finance_tables"
down_revision: Union[str, Sequence[str], None] = "0003_email_unique_index"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _money_columns() -> list:
    return [
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
    ]


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


def _source_columns() -> list:
    return [
        sa.Column("source_document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_page", sa.Integer(), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "revenue",
        *_money_columns(),
        sa.Column("record_date", sa.Date(), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("fiscal_quarter", sa.Integer(), nullable=True),
        sa.Column("segment", sa.String(100), nullable=True),
        sa.Column("region", sa.String(100), nullable=True),
        sa.Column("category", sa.String(100), nullable=True),
        *_source_columns(),
        *_stamp_columns(),
        sa.CheckConstraint("amount > 0", name="ck_revenue_amount_positive"),
        sa.CheckConstraint(
            "fiscal_quarter IS NULL OR fiscal_year IS NOT NULL",
            name="ck_revenue_quarter_needs_year",
        ),
        sa.CheckConstraint(
            "fiscal_quarter IS NULL OR (fiscal_quarter BETWEEN 1 AND 4)",
            name="ck_revenue_quarter_range",
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_revenue_company_id", "revenue", ["company_id"])
    op.create_index("ix_revenue_company_date", "revenue", ["company_id", "record_date"])
    op.create_index("ix_revenue_company_segment", "revenue", ["company_id", "segment"])
    op.create_index("ix_revenue_company_region", "revenue", ["company_id", "region"])
    op.create_index(
        "ix_revenue_company_fiscal_year", "revenue", ["company_id", "fiscal_year"]
    )

    op.create_table(
        "expenses",
        *_money_columns(),
        sa.Column("record_date", sa.Date(), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("fiscal_quarter", sa.Integer(), nullable=True),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("department", sa.String(100), nullable=True),
        sa.Column("region", sa.String(100), nullable=True),
        sa.Column("vendor", sa.String(200), nullable=True),
        sa.Column("description", sa.String(1000), nullable=True),
        *_source_columns(),
        *_stamp_columns(),
        sa.CheckConstraint("amount > 0", name="ck_expenses_amount_positive"),
        sa.CheckConstraint(
            "fiscal_quarter IS NULL OR fiscal_year IS NOT NULL",
            name="ck_expenses_quarter_needs_year",
        ),
        sa.CheckConstraint(
            "fiscal_quarter IS NULL OR (fiscal_quarter BETWEEN 1 AND 4)",
            name="ck_expenses_quarter_range",
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_expenses_company_id", "expenses", ["company_id"])
    op.create_index(
        "ix_expenses_company_date", "expenses", ["company_id", "record_date"]
    )
    op.create_index(
        "ix_expenses_company_category", "expenses", ["company_id", "category"]
    )
    op.create_index(
        "ix_expenses_company_department", "expenses", ["company_id", "department"]
    )
    op.create_index("ix_expenses_company_region", "expenses", ["company_id", "region"])

    op.create_table(
        "transactions",
        *_money_columns(),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("account", sa.String(100), nullable=True),
        sa.Column("description", sa.String(1000), nullable=True),
        sa.Column("reference", sa.String(200), nullable=True),
        *_source_columns(),
        *_stamp_columns(),
        sa.CheckConstraint("amount > 0", name="ck_transactions_amount_positive"),
        sa.CheckConstraint(
            "type IN ('income', 'expense', 'transfer')",
            name="ck_transactions_type",
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_transactions_company_id", "transactions", ["company_id"])
    op.create_index(
        "ix_transactions_company_occurred",
        "transactions",
        ["company_id", "occurred_at"],
    )
    op.create_index(
        "ix_transactions_company_type", "transactions", ["company_id", "type"]
    )
    op.create_index(
        "ix_transactions_company_category", "transactions", ["company_id", "category"]
    )

    op.create_table(
        "financial_metrics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("period", sa.Date(), nullable=False),
        sa.Column("metric_name", sa.String(64), nullable=False),
        sa.Column("value", sa.Numeric(24, 8), nullable=False),
        sa.Column("unit", sa.String(16), nullable=True),
        sa.Column("computed_by", sa.String(16), nullable=False),
        sa.Column("inputs_ref", postgresql.JSONB(), nullable=True),
        *_stamp_columns(),
        sa.CheckConstraint(
            "char_length(metric_name) > 0", name="ck_metrics_name_nonempty"
        ),
        sa.CheckConstraint(
            "computed_by IN ('reported', 'calculated', 'system')",
            name="ck_metrics_computed_by",
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "company_id",
            "period",
            "metric_name",
            name="uq_metrics_company_period_name",
        ),
    )
    op.create_index(
        "ix_financial_metrics_company_id", "financial_metrics", ["company_id"]
    )
    op.create_index(
        "ix_metrics_company_metric",
        "financial_metrics",
        ["company_id", "metric_name"],
    )


def downgrade() -> None:
    for table, indexes in (
        (
            "financial_metrics",
            ["ix_financial_metrics_company_id", "ix_metrics_company_metric"],
        ),
        (
            "transactions",
            [
                "ix_transactions_company_id",
                "ix_transactions_company_occurred",
                "ix_transactions_company_type",
                "ix_transactions_company_category",
            ],
        ),
        (
            "expenses",
            [
                "ix_expenses_company_id",
                "ix_expenses_company_date",
                "ix_expenses_company_category",
                "ix_expenses_company_department",
                "ix_expenses_company_region",
            ],
        ),
        (
            "revenue",
            [
                "ix_revenue_company_id",
                "ix_revenue_company_date",
                "ix_revenue_company_segment",
                "ix_revenue_company_region",
                "ix_revenue_company_fiscal_year",
            ],
        ),
    ):
        for index in indexes:
            op.drop_index(index, table_name=table)
        op.drop_table(table)
