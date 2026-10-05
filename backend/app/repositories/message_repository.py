"""Conversation-message persistence. Scoped by (company_id, conversation_id).

Append path serializes writers per conversation: callers lock the parent
conversation row FOR UPDATE before computing the next sequence, so two
simultaneous appends cannot collide; the UNIQUE(conversation_id, sequence)
constraint remains as a backstop (failures surface as errors, never as
silently duplicated or reordered history).
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.conversation import Conversation
from app.models.conversation_message import ConversationMessage, MessageRole


def lock_conversation(
    session: Session, *, company_id: uuid.UUID, conversation_id: uuid.UUID
) -> Conversation | None:
    return session.execute(
        select(Conversation)
        .where(
            Conversation.id == conversation_id,
            Conversation.company_id == company_id,
        )
        .with_for_update()
    ).scalar_one_or_none()


def next_sequence(session: Session, *, conversation_id: uuid.UUID) -> int:
    current = session.execute(
        select(func.coalesce(func.max(ConversationMessage.sequence), -1)).where(
            ConversationMessage.conversation_id == conversation_id
        )
    ).scalar_one()
    return int(current) + 1


def append(
    session: Session,
    *,
    conversation_id: uuid.UUID,
    company_id: uuid.UUID,
    role: MessageRole,
    content: str,
) -> ConversationMessage:
    message = ConversationMessage(
        conversation_id=conversation_id,
        company_id=company_id,
        role=role,
        content=content,
        sequence=next_sequence(session, conversation_id=conversation_id),
    )
    session.add(message)
    session.flush()
    return message


def list_ordered(
    session: Session,
    *,
    company_id: uuid.UUID,
    conversation_id: uuid.UUID,
    limit: int | None = None,
) -> list[ConversationMessage]:
    """Newest-first window (limit) returned oldest-first for prompt order."""
    stmt = (
        select(ConversationMessage)
        .where(
            ConversationMessage.conversation_id == conversation_id,
            ConversationMessage.company_id == company_id,
        )
        .order_by(ConversationMessage.sequence.desc())
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    rows = list(session.execute(stmt).scalars().all())
    return list(reversed(rows))


def count_for_conversation(
    session: Session, *, company_id: uuid.UUID, conversation_id: uuid.UUID
) -> int:
    return session.execute(
        select(func.count())
        .select_from(ConversationMessage)
        .where(
            ConversationMessage.conversation_id == conversation_id,
            ConversationMessage.company_id == company_id,
        )
    ).scalar_one()
