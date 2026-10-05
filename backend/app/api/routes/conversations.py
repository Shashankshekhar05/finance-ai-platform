"""Conversation routes. Thin: guard → one service call → typed DTO.

- POST /conversations (any role): create an owned thread in my company.
- GET /conversations (any role): mine, or all-company for admins. Paged.
- GET /conversations/{id}: detail with bounded recent messages.
- DELETE /conversations/{id}: own thread, or any company thread for admins.
Cross-tenant or foreign-user IDs answer uniform 404 (service-enforced).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_viewer
from app.schemas.conversation import (
    ConversationCreate,
    ConversationDetailRead,
    ConversationRead,
)
from app.schemas.finance_shared import Page, Pagination
from app.services import conversation_service
from app.services.tenancy import TenantContext

router = APIRouter(tags=["conversations"])


@router.post("/conversations", response_model=ConversationRead, status_code=201)
def create_conversation(
    payload: ConversationCreate,
    ctx: TenantContext = Depends(require_viewer),
    session: Session = Depends(get_db),
) -> ConversationRead:
    title = payload.title.strip() if payload.title else None
    return conversation_service.create_conversation(
        session, ctx=ctx, title=title or None
    )


@router.get("/conversations", response_model=Page[ConversationRead])
def list_conversations(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    ctx: TenantContext = Depends(require_viewer),
    session: Session = Depends(get_db),
) -> Page[ConversationRead]:
    return conversation_service.list_conversations(
        session, ctx=ctx, paging=Pagination(limit=limit, offset=offset)
    )


@router.get("/conversations/{conversation_id}", response_model=ConversationDetailRead)
def get_conversation(
    conversation_id: uuid.UUID,
    ctx: TenantContext = Depends(require_viewer),
    session: Session = Depends(get_db),
) -> ConversationDetailRead:
    return conversation_service.get_conversation_detail(
        session, ctx=ctx, conversation_id=conversation_id
    )


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: uuid.UUID,
    ctx: TenantContext = Depends(require_viewer),
    session: Session = Depends(get_db),
) -> None:
    conversation_service.delete_conversation(
        session, ctx=ctx, conversation_id=conversation_id
    )
    return None
