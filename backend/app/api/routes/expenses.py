"""Expense routes. Same guard pattern as revenue routes."""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin, require_analyst, require_viewer
from app.schemas.expense import (
    ExpenseCreate,
    ExpenseFilter,
    ExpenseRead,
    ExpenseSort,
    ExpenseUpdate,
)
from app.schemas.finance_shared import Page, Pagination, SortOrder
from app.services import expense_service
from app.services.tenancy import TenantContext

router = APIRouter(tags=["expenses"])


@router.get("/expenses", response_model=Page[ExpenseRead])
def list_expenses(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    sort: Annotated[ExpenseSort, Query()] = "record_date",
    order: Annotated[SortOrder, Query()] = "desc",
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    fiscal_year: Annotated[int | None, Query(ge=1900, le=2100)] = None,
    fiscal_quarter: Annotated[int | None, Query(ge=1, le=4)] = None,
    category: Annotated[str | None, Query(max_length=100)] = None,
    department: Annotated[str | None, Query(max_length=100)] = None,
    region: Annotated[str | None, Query(max_length=100)] = None,
    ctx: TenantContext = Depends(require_viewer),
    session: Session = Depends(get_db),
) -> Page[ExpenseRead]:
    return expense_service.list_expenses(
        session,
        company_id=ctx.company_id,
        filters=ExpenseFilter(
            date_from=date_from,
            date_to=date_to,
            fiscal_year=fiscal_year,
            fiscal_quarter=fiscal_quarter,
            category=category,
            department=department,
            region=region,
            sort=sort,
        ),
        paging=Pagination(limit=limit, offset=offset),
        order=order,
    )


@router.post(
    "/expenses", response_model=ExpenseRead, status_code=status.HTTP_201_CREATED
)
def create_expense(
    payload: ExpenseCreate,
    ctx: TenantContext = Depends(require_analyst),
    session: Session = Depends(get_db),
) -> ExpenseRead:
    return expense_service.create_expense(
        session, company_id=ctx.company_id, data=payload
    )


@router.get("/expenses/{expense_id}", response_model=ExpenseRead)
def get_expense(
    expense_id: uuid.UUID,
    ctx: TenantContext = Depends(require_viewer),
    session: Session = Depends(get_db),
) -> ExpenseRead:
    return expense_service.get_expense(
        session, company_id=ctx.company_id, expense_id=expense_id
    )


@router.patch("/expenses/{expense_id}", response_model=ExpenseRead)
def update_expense(
    expense_id: uuid.UUID,
    payload: ExpenseUpdate,
    ctx: TenantContext = Depends(require_analyst),
    session: Session = Depends(get_db),
) -> ExpenseRead:
    return expense_service.update_expense(
        session, company_id=ctx.company_id, expense_id=expense_id, data=payload
    )


@router.delete("/expenses/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_expense(
    expense_id: uuid.UUID,
    ctx: TenantContext = Depends(require_admin),
    session: Session = Depends(get_db),
) -> None:
    expense_service.delete_expense(
        session, company_id=ctx.company_id, expense_id=expense_id
    )
