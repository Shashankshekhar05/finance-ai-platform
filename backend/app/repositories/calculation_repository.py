"""Aggregation queries for the calculation engine.

One typed registry maps each Dataset enum to its model + columns — no
client string ever reaches SQL construction. All queries filter
company_id first; aggregates run in PostgreSQL (no row hauling); NUMERIC
results come back as Decimal (never float).
"""

import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.expense import Expense
from app.models.revenue import Revenue
from app.models.transaction import Transaction
from app.schemas.calculation import Dataset, Filters


@dataclass(frozen=True)
class Aggregate:
    total: Decimal | None
    count: int
    average: Decimal | None
    minimum: Decimal | None
    maximum: Decimal | None
    currencies: tuple[str, ...]


@dataclass(frozen=True)
class DatasetSpec:
    model: type
    date_column: str  # "record_date" (DATE) or "occurred_at" (timestamptz)
    amount_column: str
    # request-filter name -> model column name
    filters: dict[str, str] = field(default_factory=dict)
    # group-by name -> model column name
    groups: dict[str, str] = field(default_factory=dict)


DATASETS: dict[Dataset, DatasetSpec] = {
    Dataset.revenue: DatasetSpec(
        model=Revenue,
        date_column="record_date",
        amount_column="amount",
        filters={
            "fiscal_year": "fiscal_year",
            "quarter": "fiscal_quarter",
            "date_from": "record_date",
            "date_to": "record_date",
            "category": "category",
            "segment": "segment",
            "region": "region",
            "currency": "currency",
        },
        groups={
            "region": "region",
            "segment": "segment",
            "category": "category",
            "fiscal_year": "fiscal_year",
            "fiscal_quarter": "fiscal_quarter",
        },
    ),
    Dataset.expense: DatasetSpec(
        model=Expense,
        date_column="record_date",
        amount_column="amount",
        filters={
            "fiscal_year": "fiscal_year",
            "quarter": "fiscal_quarter",
            "date_from": "record_date",
            "date_to": "record_date",
            "category": "category",
            "department": "department",
            "region": "region",
            "vendor": "vendor",
            "currency": "currency",
        },
        groups={
            "category": "category",
            "department": "department",
            "region": "region",
            "fiscal_year": "fiscal_year",
            "fiscal_quarter": "fiscal_quarter",
        },
    ),
    Dataset.transaction: DatasetSpec(
        model=Transaction,
        date_column="occurred_at",
        amount_column="amount",
        filters={
            "date_from": "occurred_at",
            "date_to": "occurred_at",
            "transaction_type": "type",
            "category": "category",
            "account": "account",
            "currency": "currency",
        },
        groups={
            "category": "category",
            "account": "account",
            "transaction_type": "type",
        },
    ),
}


def _conditions(spec: DatasetSpec, company_id: uuid.UUID, filters: Filters) -> list:
    data = filters.model_dump(exclude_unset=True, exclude_none=True)
    conditions = [spec.model.company_id == company_id]
    for name, column_name in spec.filters.items():
        if name not in data:
            continue
        column = getattr(spec.model, column_name)
        if name == "date_from":
            conditions.append(column >= data[name])
        elif name == "date_to":
            conditions.append(column <= data[name])
        else:
            conditions.append(column == data[name])
    return conditions


def aggregate(
    session: Session,
    *,
    dataset: Dataset,
    company_id: uuid.UUID,
    filters: Filters,
) -> Aggregate:
    """Single SUM/COUNT/AVG/MIN/MAX + distinct currencies in two queries."""
    spec = DATASETS[dataset]
    amount = getattr(spec.model, spec.amount_column)
    conditions = _conditions(spec, company_id, filters)
    row = session.execute(
        select(
            func.sum(amount),
            func.count(spec.model.id),
            func.avg(amount),
            func.min(amount),
            func.max(amount),
        ).where(*conditions)
    ).one()
    currencies = (
        session.execute(
            select(getattr(spec.model, "currency")).where(*conditions).distinct()
        )
        .scalars()
        .all()
    )
    return Aggregate(
        total=row[0],
        count=row[1],
        average=row[2],
        minimum=row[3],
        maximum=row[4],
        currencies=tuple(currencies),
    )


def aggregate_grouped(
    session: Session,
    *,
    dataset: Dataset,
    company_id: uuid.UUID,
    filters: Filters,
    group_by: list[str],
) -> list[tuple[tuple, Decimal | None, int]]:
    """[(dimension values, sum, count)] ordered by dimensions ascending."""
    spec = DATASETS[dataset]
    columns = [getattr(spec.model, spec.groups[name]) for name in group_by]
    amount = getattr(spec.model, spec.amount_column)
    rows = session.execute(
        select(*columns, func.sum(amount), func.count(spec.model.id))
        .where(*_conditions(spec, company_id, filters))
        .group_by(*columns)
        .order_by(*[col.asc() for col in columns])
    ).all()
    width = len(columns)
    return [(tuple(row[:width]), row[width], row[width + 1]) for row in rows]
