"""Transaction routes. Same guard pattern as revenue routes."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin, require_analyst, require_viewer
from app.models.transaction import TransactionType
from app.schemas.finance_shared import Page, Pagination, SortOrder
from app.schemas.transaction import (
    TransactionCreate,
    TransactionFilter,
    TransactionRead,
    TransactionSort,
    TransactionUpdate,
)
from app.services import transaction_service
from app.services.tenancy import TenantContext

router = APIRouter(tags=["transactions"])


@router.get("/transactions", response_model=Page[TransactionRead])
def list_transactions(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    sort: Annotated[TransactionSort, Query()] = "occurred_at",
    order: Annotated[SortOrder, Query()] = "desc",
    date_from: Annotated[datetime | None, Query()] = None,
    date_to: Annotated[datetime | None, Query()] = None,
    type: Annotated[TransactionType | None, Query()] = None,  # noqa: A002
    category: Annotated[str | None, Query(max_length=100)] = None,
    account: Annotated[str | None, Query(max_length=100)] = None,
    ctx: TenantContext = Depends(require_viewer),
    session: Session = Depends(get_db),
) -> Page[TransactionRead]:
    return transaction_service.list_transactions(
        session,
        company_id=ctx.company_id,
        filters=TransactionFilter(
            date_from=date_from,
            date_to=date_to,
            type=type,
            category=category,
            account=account,
            sort=sort,
        ),
        paging=Pagination(limit=limit, offset=offset),
        order=order,
    )


@router.post(
    "/transactions", response_model=TransactionRead, status_code=status.HTTP_201_CREATED
)
def create_transaction(
    payload: TransactionCreate,
    ctx: TenantContext = Depends(require_analyst),
    session: Session = Depends(get_db),
) -> TransactionRead:
    return transaction_service.create_transaction(
        session, company_id=ctx.company_id, data=payload
    )


@router.get("/transactions/{transaction_id}", response_model=TransactionRead)
def get_transaction(
    transaction_id: uuid.UUID,
    ctx: TenantContext = Depends(require_viewer),
    session: Session = Depends(get_db),
) -> TransactionRead:
    return transaction_service.get_transaction(
        session, company_id=ctx.company_id, transaction_id=transaction_id
    )


@router.patch("/transactions/{transaction_id}", response_model=TransactionRead)
def update_transaction(
    transaction_id: uuid.UUID,
    payload: TransactionUpdate,
    ctx: TenantContext = Depends(require_analyst),
    session: Session = Depends(get_db),
) -> TransactionRead:
    return transaction_service.update_transaction(
        session, company_id=ctx.company_id, transaction_id=transaction_id, data=payload
    )


@router.delete("/transactions/{transaction_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_transaction(
    transaction_id: uuid.UUID,
    ctx: TenantContext = Depends(require_admin),
    session: Session = Depends(get_db),
) -> None:
    transaction_service.delete_transaction(
        session, company_id=ctx.company_id, transaction_id=transaction_id
    )
