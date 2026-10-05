"""Transaction service: company-scoped CRUD. Same conventions as revenue_service."""

import uuid

from fastapi import status
from sqlalchemy.orm import Session

from app.core.errors import raise_api_error
from app.models.transaction import Transaction
from app.repositories import transaction_repository
from app.schemas.finance_shared import Page, Pagination, SortOrder
from app.schemas.transaction import (
    TransactionCreate,
    TransactionFilter,
    TransactionRead,
    TransactionUpdate,
)


def _to_read(record: Transaction) -> TransactionRead:
    return TransactionRead(
        id=record.id,
        company_id=record.company_id,
        occurred_at=record.occurred_at,
        amount=str(record.amount),
        currency=record.currency,
        type=record.type.value,
        category=record.category,
        account=record.account,
        description=record.description,
        reference=record.reference,
        source_document_id=record.source_document_id,
        source_page=record.source_page,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _required(
    session: Session, *, company_id: uuid.UUID, transaction_id: uuid.UUID
) -> Transaction:
    record = transaction_repository.get(
        session, company_id=company_id, transaction_id=transaction_id
    )
    if record is None:
        raise raise_api_error(status.HTTP_404_NOT_FOUND, "not_found")
    return record


def create_transaction(
    session: Session, *, company_id: uuid.UUID, data: TransactionCreate
) -> TransactionRead:
    record = transaction_repository.create(session, company_id=company_id, data=data)
    session.commit()
    session.refresh(record)
    return _to_read(record)


def get_transaction(
    session: Session, *, company_id: uuid.UUID, transaction_id: uuid.UUID
) -> TransactionRead:
    return _to_read(
        _required(session, company_id=company_id, transaction_id=transaction_id)
    )


def update_transaction(
    session: Session,
    *,
    company_id: uuid.UUID,
    transaction_id: uuid.UUID,
    data: TransactionUpdate,
) -> TransactionRead:
    record = transaction_repository.update(
        session,
        record=_required(session, company_id=company_id, transaction_id=transaction_id),
        data=data,
    )
    session.commit()
    session.refresh(record)
    return _to_read(record)


def delete_transaction(
    session: Session, *, company_id: uuid.UUID, transaction_id: uuid.UUID
) -> None:
    transaction_repository.delete(
        session,
        record=_required(session, company_id=company_id, transaction_id=transaction_id),
    )
    session.commit()


def list_transactions(
    session: Session,
    *,
    company_id: uuid.UUID,
    filters: TransactionFilter,
    paging: Pagination,
    order: SortOrder,
) -> Page[TransactionRead]:
    items, total = transaction_repository.list_paged(
        session,
        company_id=company_id,
        filters=filters,
        limit=paging.limit,
        offset=paging.offset,
        order=order,
    )
    return Page[TransactionRead](
        items=[_to_read(record) for record in items],
        total=total,
        limit=paging.limit,
        offset=paging.offset,
    )
