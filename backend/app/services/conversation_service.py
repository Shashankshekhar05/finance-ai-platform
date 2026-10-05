"""Conversation service: threads, access control, bounded context windows.

Access rule (simple, documented): a conversation belongs to one user in one
company. The owning user (any role) plus company admins may read/use/delete
it. No sharing, no cross-company access — cross-tenant IDs answer 404.

Message appends lock the parent conversation row FOR UPDATE inside the
request transaction, so concurrent writers serialize per thread; the
UNIQUE(conversation_id, sequence) constraint backstops ordering. This is
documented best-effort serialization, not a distributed lock claim.

The context window is supporting context ONLY: bounded recent turns,
oldest-trimmed to message and character budgets. History never becomes
authoritative evidence (enforced downstream by keeping it in a separate
prompt block from the EvidencePacket).
"""

import logging
import uuid
from typing import TYPE_CHECKING

from fastapi import status
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import raise_api_error
from app.models.conversation import MessageRole
from app.models.conversation_message import ConversationMessage
from app.models.user_role import Role
from app.repositories import conversation_repository, message_repository
from app.schemas.conversation import (
    ConversationDetailRead,
    ConversationRead,
    MessageRead,
)
from app.schemas.finance_shared import Page, Pagination
from app.services.tenancy import TenantContext

if TYPE_CHECKING:
    from app.models.conversation import Conversation

logger = logging.getLogger(__name__)


def _to_message_read(message: ConversationMessage) -> MessageRead:
    return MessageRead(
        id=message.id,
        role=message.role.value,
        content=message.content,
        sequence=message.sequence,
        created_at=message.created_at,
    )


def _to_conversation_read(
    record: "Conversation", *, message_count: int
) -> ConversationRead:
    return ConversationRead(
        id=record.id,
        company_id=record.company_id,
        user_id=record.user_id,
        title=record.title,
        message_count=message_count,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _require_access(
    session: Session, *, ctx: TenantContext, conversation_id: uuid.UUID
) -> "Conversation":
    record = conversation_repository.get(
        session, company_id=ctx.company_id, conversation_id=conversation_id
    )
    if record is None:
        raise raise_api_error(status.HTTP_404_NOT_FOUND, "not_found")
    if record.user_id != ctx.user.id and ctx.role != Role.admin:
        # Same safe 404: never reveal another user's thread exists.
        raise raise_api_error(status.HTTP_404_NOT_FOUND, "not_found")
    return record


def create_conversation(
    session: Session, *, ctx: TenantContext, title: str | None
) -> ConversationRead:
    record = conversation_repository.create(
        session, company_id=ctx.company_id, user_id=ctx.user.id, title=title
    )
    session.commit()
    session.refresh(record)
    logger.info(
        "conversation created conversation_id=%s company_id=%s",
        record.id,
        ctx.company_id,
    )
    return _to_conversation_read(record, message_count=0)


def list_conversations(
    session: Session, *, ctx: TenantContext, paging: Pagination
) -> Page[ConversationRead]:
    if ctx.role == Role.admin:
        items, total = conversation_repository.list_for_company(
            session,
            company_id=ctx.company_id,
            limit=paging.limit,
            offset=paging.offset,
        )
    else:
        items, total = conversation_repository.list_for_user(
            session,
            company_id=ctx.company_id,
            user_id=ctx.user.id,
            limit=paging.limit,
            offset=paging.offset,
        )
    reads = []
    for item in items:
        count = message_repository.count_for_conversation(
            session, company_id=ctx.company_id, conversation_id=item.id
        )
        reads.append(_to_conversation_read(item, message_count=count))
    return Page[ConversationRead](
        items=reads, total=total, limit=paging.limit, offset=paging.offset
    )


def get_conversation_detail(
    session: Session,
    *,
    ctx: TenantContext,
    conversation_id: uuid.UUID,
    message_limit: int = 50,
) -> ConversationDetailRead:
    record = _require_access(session, ctx=ctx, conversation_id=conversation_id)
    messages = message_repository.list_ordered(
        session,
        company_id=ctx.company_id,
        conversation_id=conversation_id,
        limit=message_limit,
    )
    base = _to_conversation_read(
        record,
        message_count=message_repository.count_for_conversation(
            session, company_id=ctx.company_id, conversation_id=conversation_id
        ),
    )
    return ConversationDetailRead(
        **base.model_dump(), messages=[_to_message_read(m) for m in messages]
    )


def delete_conversation(
    session: Session, *, ctx: TenantContext, conversation_id: uuid.UUID
) -> None:
    record = _require_access(session, ctx=ctx, conversation_id=conversation_id)
    conversation_repository.delete(session, record=record)
    session.commit()
    logger.info(
        "conversation deleted conversation_id=%s company_id=%s",
        conversation_id,
        ctx.company_id,
    )


def append_message(
    session: Session,
    *,
    ctx: TenantContext,
    conversation_id: uuid.UUID,
    role: MessageRole,
    content: str,
) -> MessageRead:
    record = message_repository.lock_conversation(
        session, company_id=ctx.company_id, conversation_id=conversation_id
    )
    if record is None:
        raise raise_api_error(status.HTTP_404_NOT_FOUND, "not_found")
    if record.user_id != ctx.user.id and ctx.role != Role.admin:
        raise raise_api_error(status.HTTP_404_NOT_FOUND, "not_found")
    message = message_repository.append(
        session,
        conversation_id=record.id,
        company_id=ctx.company_id,
        role=role,
        content=content,
    )
    session.commit()
    session.refresh(message)
    return _to_message_read(message)


def get_context_window(
    session: Session,
    *,
    ctx: TenantContext,
    conversation_id: uuid.UUID,
    settings: Settings,
) -> list[tuple[str, str]]:
    """Bounded recent turns, oldest-first, trimmed to budgets.

    Takes the N most recent messages, then drops oldest whole messages
    until the character budget fits. Returns (role, content) pairs —
    supporting context only, never evidence.
    """
    _require_access(session, ctx=ctx, conversation_id=conversation_id)
    messages = message_repository.list_ordered(
        session,
        company_id=ctx.company_id,
        conversation_id=conversation_id,
        limit=settings.ai_max_conversation_messages,
    )
    window = [(m.role.value, m.content) for m in messages]
    budget = settings.ai_max_conversation_chars
    while window and sum(len(content) for _, content in window) > budget:
        window.pop(0)
    return window
