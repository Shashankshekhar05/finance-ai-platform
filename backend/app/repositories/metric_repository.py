"""Financial-metric persistence. Company-scoped reads; service-owned writes.

`record` upserts on (company_id, period, metric_name): deterministic
recomputation of the same metric converges on one row instead of erroring.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.financial_metric import FinancialMetric
from app.schemas.finance_shared import SortOrder
from app.schemas.financial_metric import MetricFilter, MetricRecordInput

_SORT_COLUMNS = {
    "period": FinancialMetric.period,
    "metric_name": FinancialMetric.metric_name,
    "value": FinancialMetric.value,
}


def get(
    session: Session, *, company_id: uuid.UUID, metric_id: uuid.UUID
) -> FinancialMetric | None:
    return session.execute(
        select(FinancialMetric).where(
            FinancialMetric.id == metric_id, FinancialMetric.company_id == company_id
        )
    ).scalar_one_or_none()


def record(
    session: Session, *, company_id: uuid.UUID, data: MetricRecordInput
) -> FinancialMetric:
    """Insert or, on (company, period, name) conflict, refresh the value."""
    stmt = pg_insert(FinancialMetric).values(
        company_id=company_id,
        period=data.period,
        metric_name=data.metric_name,
        value=data.value,
        unit=data.unit,
        computed_by=data.computed_by,
        inputs_ref=data.inputs_ref,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["company_id", "period", "metric_name"],
        set_={
            "value": stmt.excluded.value,
            "unit": stmt.excluded.unit,
            "computed_by": stmt.excluded.computed_by,
            "inputs_ref": stmt.excluded.inputs_ref,
        },
    ).returning(FinancialMetric)
    record = session.execute(stmt).scalar_one()
    session.flush()
    return record


def list_paged(
    session: Session,
    *,
    company_id: uuid.UUID,
    filters: MetricFilter,
    limit: int,
    offset: int,
    order: SortOrder,
) -> tuple[list[FinancialMetric], int]:
    conditions = [FinancialMetric.company_id == company_id]
    if filters.metric_name is not None:
        conditions.append(FinancialMetric.metric_name == filters.metric_name)
    if filters.period_from is not None:
        conditions.append(FinancialMetric.period >= filters.period_from)
    if filters.period_to is not None:
        conditions.append(FinancialMetric.period <= filters.period_to)
    if filters.computed_by is not None:
        conditions.append(FinancialMetric.computed_by == filters.computed_by)

    sort_col = _SORT_COLUMNS[filters.sort]
    ordering = sort_col.desc() if order == "desc" else sort_col.asc()
    stmt = (
        select(FinancialMetric)
        .where(*conditions)
        .order_by(ordering, FinancialMetric.id.asc())
    )
    total = session.execute(
        select(func.count()).select_from(stmt.subquery())
    ).scalar_one()
    items = list(session.execute(stmt.limit(limit).offset(offset)).scalars().all())
    return items, total
