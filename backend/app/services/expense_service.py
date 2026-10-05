"""Expense service: company-scoped CRUD. Same conventions as revenue_service."""

import uuid

from fastapi import status
from sqlalchemy.orm import Session

from app.core.errors import raise_api_error
from app.models.expense import Expense
from app.repositories import expense_repository
from app.schemas.expense import ExpenseCreate, ExpenseFilter, ExpenseRead, ExpenseUpdate
from app.schemas.finance_shared import Page, Pagination, SortOrder


def _to_read(record: Expense) -> ExpenseRead:
    return ExpenseRead(
        id=record.id,
        company_id=record.company_id,
        amount=str(record.amount),
        currency=record.currency,
        record_date=record.record_date,
        fiscal_year=record.fiscal_year,
        fiscal_quarter=record.fiscal_quarter,
        category=record.category,
        department=record.department,
        region=record.region,
        vendor=record.vendor,
        description=record.description,
        source_document_id=record.source_document_id,
        source_page=record.source_page,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _required(
    session: Session, *, company_id: uuid.UUID, expense_id: uuid.UUID
) -> Expense:
    record = expense_repository.get(
        session, company_id=company_id, expense_id=expense_id
    )
    if record is None:
        raise raise_api_error(status.HTTP_404_NOT_FOUND, "not_found")
    return record


def create_expense(
    session: Session, *, company_id: uuid.UUID, data: ExpenseCreate
) -> ExpenseRead:
    record = expense_repository.create(session, company_id=company_id, data=data)
    session.commit()
    session.refresh(record)
    return _to_read(record)


def get_expense(
    session: Session, *, company_id: uuid.UUID, expense_id: uuid.UUID
) -> ExpenseRead:
    return _to_read(_required(session, company_id=company_id, expense_id=expense_id))


def update_expense(
    session: Session,
    *,
    company_id: uuid.UUID,
    expense_id: uuid.UUID,
    data: ExpenseUpdate,
) -> ExpenseRead:
    record = expense_repository.update(
        session,
        record=_required(session, company_id=company_id, expense_id=expense_id),
        data=data,
    )
    session.commit()
    session.refresh(record)
    return _to_read(record)


def delete_expense(
    session: Session, *, company_id: uuid.UUID, expense_id: uuid.UUID
) -> None:
    expense_repository.delete(
        session, record=_required(session, company_id=company_id, expense_id=expense_id)
    )
    session.commit()


def list_expenses(
    session: Session,
    *,
    company_id: uuid.UUID,
    filters: ExpenseFilter,
    paging: Pagination,
    order: SortOrder,
) -> Page[ExpenseRead]:
    items, total = expense_repository.list_paged(
        session,
        company_id=company_id,
        filters=filters,
        limit=paging.limit,
        offset=paging.offset,
        order=order,
    )
    return Page[ExpenseRead](
        items=[_to_read(record) for record in items],
        total=total,
        limit=paging.limit,
        offset=paging.offset,
    )
