"""Transaction persistence. Company-scoped on every path; flush, never commit."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.transaction import Transaction
from app.schemas.finance_shared import SortOrder
from app.schemas.transaction import (
    TransactionCreate,
    TransactionFilter,
    TransactionUpdate,
)

_SORT_COLUMNS = {
    "occurred_at": Transaction.occurred_at,
    "amount": Transaction.amount,
    "created_at": Transaction.created_at,
}


def get(
    session: Session, *, company_id: uuid.UUID, transaction_id: uuid.UUID
) -> Transaction | None:
    return session.execute(
        select(Transaction).where(
            Transaction.id == transaction_id, Transaction.company_id == company_id
        )
    ).scalar_one_or_none()


def create(
    session: Session, *, company_id: uuid.UUID, data: TransactionCreate
) -> Transaction:
    record = Transaction(company_id=company_id, **data.model_dump())
    session.add(record)
    session.flush()
    return record


def update(
    session: Session, *, record: Transaction, data: TransactionUpdate
) -> Transaction:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(record, field, value)
    session.flush()
    return record


def delete(session: Session, *, record: Transaction) -> None:
    session.delete(record)
    session.flush()


def list_paged(
    session: Session,
    *,
    company_id: uuid.UUID,
    filters: TransactionFilter,
    limit: int,
    offset: int,
    order: SortOrder,
) -> tuple[list[Transaction], int]:
    conditions = [Transaction.company_id == company_id]
    if filters.date_from is not None:
        conditions.append(Transaction.occurred_at >= filters.date_from)
    if filters.date_to is not None:
        conditions.append(Transaction.occurred_at <= filters.date_to)
    if filters.type is not None:
        conditions.append(Transaction.type == filters.type)
    if filters.category is not None:
        conditions.append(Transaction.category == filters.category)
    if filters.account is not None:
        conditions.append(Transaction.account == filters.account)

    sort_col = _SORT_COLUMNS[filters.sort]
    ordering = sort_col.desc() if order == "desc" else sort_col.asc()
    stmt = (
        select(Transaction).where(*conditions).order_by(ordering, Transaction.id.asc())
    )
    total = session.execute(
        select(func.count()).select_from(stmt.subquery())
    ).scalar_one()
    items = list(session.execute(stmt.limit(limit).offset(offset)).scalars().all())
    return items, total
