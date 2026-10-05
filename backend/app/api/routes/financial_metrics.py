"""Financial-metric routes. READ-ONLY in Phase 3 (viewer and above).

Writes go through the metric service (tests today, the deterministic
calculation engine tomorrow) — there is intentionally no POST/PATCH/DELETE.
"""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_viewer
from app.models.financial_metric import ComputedBy
from app.schemas.finance_shared import Page, Pagination, SortOrder
from app.schemas.financial_metric import MetricFilter, MetricRead, MetricSort
from app.services import metric_service
from app.services.tenancy import TenantContext

router = APIRouter(tags=["financial-metrics"])


@router.get("/financial-metrics", response_model=Page[MetricRead])
def list_metrics(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    sort: Annotated[MetricSort, Query()] = "period",
    order: Annotated[SortOrder, Query()] = "desc",
    metric_name: Annotated[str | None, Query(max_length=64)] = None,
    period_from: Annotated[date | None, Query()] = None,
    period_to: Annotated[date | None, Query()] = None,
    computed_by: Annotated[ComputedBy | None, Query()] = None,
    ctx: TenantContext = Depends(require_viewer),
    session: Session = Depends(get_db),
) -> Page[MetricRead]:
    return metric_service.list_metrics(
        session,
        company_id=ctx.company_id,
        filters=MetricFilter(
            metric_name=metric_name,
            period_from=period_from,
            period_to=period_to,
            computed_by=computed_by,
            sort=sort,
        ),
        paging=Pagination(limit=limit, offset=offset),
        order=order,
    )


@router.get("/financial-metrics/{metric_id}", response_model=MetricRead)
def get_metric(
    metric_id: uuid.UUID,
    ctx: TenantContext = Depends(require_viewer),
    session: Session = Depends(get_db),
) -> MetricRead:
    return metric_service.get_metric(
        session, company_id=ctx.company_id, metric_id=metric_id
    )
