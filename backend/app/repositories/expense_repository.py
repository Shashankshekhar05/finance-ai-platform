"""Expense persistence. Company-scoped on every path; flush, never commit."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.expense import Expense
from app.schemas.expense import ExpenseCreate, ExpenseFilter, ExpenseUpdate
from app.schemas.finance_shared import SortOrder

_SORT_COLUMNS = {
    "record_date": Expense.record_date,
    "amount": Expense.amount,
    "created_at": Expense.created_at,
}


def get(
    session: Session, *, company_id: uuid.UUID, expense_id: uuid.UUID
) -> Expense | None:
    return session.execute(
        select(Expense).where(
            Expense.id == expense_id, Expense.company_id == company_id
        )
    ).scalar_one_or_none()


def create(session: Session, *, company_id: uuid.UUID, data: ExpenseCreate) -> Expense:
    record = Expense(company_id=company_id, **data.model_dump())
    session.add(record)
    session.flush()
    return record


def update(session: Session, *, record: Expense, data: ExpenseUpdate) -> Expense:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(record, field, value)
    session.flush()
    return record


def delete(session: Session, *, record: Expense) -> None:
    session.delete(record)
    session.flush()


def list_paged(
    session: Session,
    *,
    company_id: uuid.UUID,
    filters: ExpenseFilter,
    limit: int,
    offset: int,
    order: SortOrder,
) -> tuple[list[Expense], int]:
    conditions = [Expense.company_id == company_id]
    if filters.date_from is not None:
        conditions.append(Expense.record_date >= filters.date_from)
    if filters.date_to is not None:
        conditions.append(Expense.record_date <= filters.date_to)
    if filters.fiscal_year is not None:
        conditions.append(Expense.fiscal_year == filters.fiscal_year)
    if filters.fiscal_quarter is not None:
        conditions.append(Expense.fiscal_quarter == filters.fiscal_quarter)
    if filters.category is not None:
        conditions.append(Expense.category == filters.category)
    if filters.department is not None:
        conditions.append(Expense.department == filters.department)
    if filters.region is not None:
        conditions.append(Expense.region == filters.region)

    sort_col = _SORT_COLUMNS[filters.sort]
    ordering = sort_col.desc() if order == "desc" else sort_col.asc()
    stmt = select(Expense).where(*conditions).order_by(ordering, Expense.id.asc())
    total = session.execute(
        select(func.count()).select_from(stmt.subquery())
    ).scalar_one()
    items = list(session.execute(stmt.limit(limit).offset(offset)).scalars().all())
    return items, total
