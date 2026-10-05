"""Metric service: company-scoped reads + service-level recording.

No HTTP create/update in Phase 3 (read-only API): `record_metric` exists
for tests today and the deterministic calculation engine tomorrow.
Upsert semantics live in the repository (recompute converges, never dupes).
"""

import uuid

from fastapi import status
from sqlalchemy.orm import Session

from app.core.errors import raise_api_error
from app.models.financial_metric import FinancialMetric
from app.repositories import metric_repository
from app.schemas.finance_shared import Page, Pagination, SortOrder
from app.schemas.financial_metric import MetricFilter, MetricRead, MetricRecordInput


def _to_read(record: FinancialMetric) -> MetricRead:
    return MetricRead(
        id=record.id,
        company_id=record.company_id,
        period=record.period,
        metric_name=record.metric_name,
        value=str(record.value),
        unit=record.unit,
        computed_by=record.computed_by.value,
        inputs_ref=record.inputs_ref,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def get_metric(
    session: Session, *, company_id: uuid.UUID, metric_id: uuid.UUID
) -> MetricRead:
    record = metric_repository.get(session, company_id=company_id, metric_id=metric_id)
    if record is None:
        raise raise_api_error(status.HTTP_404_NOT_FOUND, "not_found")
    return _to_read(record)


def list_metrics(
    session: Session,
    *,
    company_id: uuid.UUID,
    filters: MetricFilter,
    paging: Pagination,
    order: SortOrder,
) -> Page[MetricRead]:
    items, total = metric_repository.list_paged(
        session,
        company_id=company_id,
        filters=filters,
        limit=paging.limit,
        offset=paging.offset,
        order=order,
    )
    return Page[MetricRead](
        items=[_to_read(record) for record in items],
        total=total,
        limit=paging.limit,
        offset=paging.offset,
    )


def record_metric(
    session: Session, *, company_id: uuid.UUID, data: MetricRecordInput
) -> MetricRead:
    record = metric_repository.record(session, company_id=company_id, data=data)
    session.commit()
    session.refresh(record)
    return _to_read(record)
