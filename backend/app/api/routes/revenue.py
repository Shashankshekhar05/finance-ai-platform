"""Revenue routes. Thin: guards → one service call → typed DTO.

- GET (list + detail): viewer and above.
- POST / PATCH: analyst and above.
- DELETE: admin only.

List query params are declared explicitly (FastAPI-native, OpenAPI-clean)
and packed into validated Filter/Pagination containers in-route.
"""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin, require_analyst, require_viewer
from app.schemas.finance_shared import Page, Pagination, SortOrder
from app.schemas.revenue import (
    RevenueCreate,
    RevenueFilter,
    RevenueRead,
    RevenueSort,
    RevenueUpdate,
)
from app.services import revenue_service
from app.services.tenancy import TenantContext

router = APIRouter(tags=["revenue"])


@router.get("/revenue", response_model=Page[RevenueRead])
def list_revenue(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    sort: Annotated[RevenueSort, Query()] = "record_date",
    order: Annotated[SortOrder, Query()] = "desc",
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    fiscal_year: Annotated[int | None, Query(ge=1900, le=2100)] = None,
    fiscal_quarter: Annotated[int | None, Query(ge=1, le=4)] = None,
    region: Annotated[str | None, Query(max_length=100)] = None,
    segment: Annotated[str | None, Query(max_length=100)] = None,
    category: Annotated[str | None, Query(max_length=100)] = None,
    ctx: TenantContext = Depends(require_viewer),
    session: Session = Depends(get_db),
) -> Page[RevenueRead]:
    return revenue_service.list_revenue(
        session,
        company_id=ctx.company_id,
        filters=RevenueFilter(
            date_from=date_from,
            date_to=date_to,
            fiscal_year=fiscal_year,
            fiscal_quarter=fiscal_quarter,
            region=region,
            segment=segment,
            category=category,
            sort=sort,
        ),
        paging=Pagination(limit=limit, offset=offset),
        order=order,
    )


@router.post(
    "/revenue", response_model=RevenueRead, status_code=status.HTTP_201_CREATED
)
def create_revenue(
    payload: RevenueCreate,
    ctx: TenantContext = Depends(require_analyst),
    session: Session = Depends(get_db),
) -> RevenueRead:
    return revenue_service.create_revenue(
        session, company_id=ctx.company_id, data=payload
    )


@router.get("/revenue/{revenue_id}", response_model=RevenueRead)
def get_revenue(
    revenue_id: uuid.UUID,
    ctx: TenantContext = Depends(require_viewer),
    session: Session = Depends(get_db),
) -> RevenueRead:
    return revenue_service.get_revenue(
        session, company_id=ctx.company_id, revenue_id=revenue_id
    )


@router.patch("/revenue/{revenue_id}", response_model=RevenueRead)
def update_revenue(
    revenue_id: uuid.UUID,
    payload: RevenueUpdate,
    ctx: TenantContext = Depends(require_analyst),
    session: Session = Depends(get_db),
) -> RevenueRead:
    return revenue_service.update_revenue(
        session, company_id=ctx.company_id, revenue_id=revenue_id, data=payload
    )


@router.delete("/revenue/{revenue_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_revenue(
    revenue_id: uuid.UUID,
    ctx: TenantContext = Depends(require_admin),
    session: Session = Depends(get_db),
) -> None:
    revenue_service.delete_revenue(
        session, company_id=ctx.company_id, revenue_id=revenue_id
    )
