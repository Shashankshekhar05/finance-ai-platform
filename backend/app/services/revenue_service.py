"""Revenue service: company-scoped CRUD over the request session.

Owns the single commit per write. Raises 404 `not_found` for missing or
foreign rows (never distinguish: no existence leakage across tenants).
"""

import uuid

from fastapi import status
from sqlalchemy.orm import Session

from app.core.errors import raise_api_error
from app.models.revenue import Revenue
from app.repositories import revenue_repository
from app.schemas.finance_shared import Page, Pagination, SortOrder
from app.schemas.revenue import RevenueCreate, RevenueFilter, RevenueRead, RevenueUpdate


def _to_read(record: Revenue) -> RevenueRead:
    return RevenueRead(
        id=record.id,
        company_id=record.company_id,
        amount=str(record.amount),
        currency=record.currency,
        record_date=record.record_date,
        fiscal_year=record.fiscal_year,
        fiscal_quarter=record.fiscal_quarter,
        segment=record.segment,
        region=record.region,
        category=record.category,
        source_document_id=record.source_document_id,
        source_page=record.source_page,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _required(
    session: Session, *, company_id: uuid.UUID, revenue_id: uuid.UUID
) -> Revenue:
    record = revenue_repository.get(
        session, company_id=company_id, revenue_id=revenue_id
    )
    if record is None:
        raise raise_api_error(status.HTTP_404_NOT_FOUND, "not_found")
    return record


def create_revenue(
    session: Session, *, company_id: uuid.UUID, data: RevenueCreate
) -> RevenueRead:
    record = revenue_repository.create(session, company_id=company_id, data=data)
    session.commit()
    session.refresh(record)
    return _to_read(record)


def get_revenue(
    session: Session, *, company_id: uuid.UUID, revenue_id: uuid.UUID
) -> RevenueRead:
    return _to_read(_required(session, company_id=company_id, revenue_id=revenue_id))


def update_revenue(
    session: Session,
    *,
    company_id: uuid.UUID,
    revenue_id: uuid.UUID,
    data: RevenueUpdate,
) -> RevenueRead:
    record = revenue_repository.update(
        session,
        record=_required(session, company_id=company_id, revenue_id=revenue_id),
        data=data,
    )
    session.commit()
    session.refresh(record)
    return _to_read(record)


def delete_revenue(
    session: Session, *, company_id: uuid.UUID, revenue_id: uuid.UUID
) -> None:
    revenue_repository.delete(
        session, record=_required(session, company_id=company_id, revenue_id=revenue_id)
    )
    session.commit()


def list_revenue(
    session: Session,
    *,
    company_id: uuid.UUID,
    filters: RevenueFilter,
    paging: Pagination,
    order: SortOrder,
) -> Page[RevenueRead]:
    items, total = revenue_repository.list_paged(
        session,
        company_id=company_id,
        filters=filters,
        limit=paging.limit,
        offset=paging.offset,
        order=order,
    )
    return Page[RevenueRead](
        items=[_to_read(record) for record in items],
        total=total,
        limit=paging.limit,
        offset=paging.offset,
    )
