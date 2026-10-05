"""Revenue persistence. Every read/write is company-scoped: there is no
unscoped access path. Repos flush, never commit (service owns the commit)."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.revenue import Revenue
from app.schemas.finance_shared import SortOrder
from app.schemas.revenue import RevenueCreate, RevenueFilter, RevenueUpdate

_SORT_COLUMNS = {
    "record_date": Revenue.record_date,
    "amount": Revenue.amount,
    "created_at": Revenue.created_at,
}


def get(
    session: Session, *, company_id: uuid.UUID, revenue_id: uuid.UUID
) -> Revenue | None:
    return session.execute(
        select(Revenue).where(
            Revenue.id == revenue_id, Revenue.company_id == company_id
        )
    ).scalar_one_or_none()


def create(session: Session, *, company_id: uuid.UUID, data: RevenueCreate) -> Revenue:
    record = Revenue(company_id=company_id, **data.model_dump())
    session.add(record)
    session.flush()
    return record


def update(session: Session, *, record: Revenue, data: RevenueUpdate) -> Revenue:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(record, field, value)
    session.flush()
    return record


def delete(session: Session, *, record: Revenue) -> None:
    session.delete(record)
    session.flush()


def list_paged(
    session: Session,
    *,
    company_id: uuid.UUID,
    filters: RevenueFilter,
    limit: int,
    offset: int,
    order: SortOrder,
) -> tuple[list[Revenue], int]:
    conditions = [Revenue.company_id == company_id]
    if filters.date_from is not None:
        conditions.append(Revenue.record_date >= filters.date_from)
    if filters.date_to is not None:
        conditions.append(Revenue.record_date <= filters.date_to)
    if filters.fiscal_year is not None:
        conditions.append(Revenue.fiscal_year == filters.fiscal_year)
    if filters.fiscal_quarter is not None:
        conditions.append(Revenue.fiscal_quarter == filters.fiscal_quarter)
    if filters.region is not None:
        conditions.append(Revenue.region == filters.region)
    if filters.segment is not None:
        conditions.append(Revenue.segment == filters.segment)
    if filters.category is not None:
        conditions.append(Revenue.category == filters.category)

    sort_col = _SORT_COLUMNS[filters.sort]
    ordering = sort_col.desc() if order == "desc" else sort_col.asc()
    # id tiebreaker: deterministic order across pages.
    stmt = select(Revenue).where(*conditions).order_by(ordering, Revenue.id.asc())
    total = session.execute(
        select(func.count()).select_from(stmt.subquery())
    ).scalar_one()
    items = list(session.execute(stmt.limit(limit).offset(offset)).scalars().all())
    return items, total
