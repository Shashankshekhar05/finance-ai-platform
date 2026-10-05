"""Conversation persistence. Company-scoped on every path; flush, never commit."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.conversation import Conversation


def get(
    session: Session, *, company_id: uuid.UUID, conversation_id: uuid.UUID
) -> Conversation | None:
    return session.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.company_id == company_id,
        )
    ).scalar_one_or_none()


def create(
    session: Session,
    *,
    company_id: uuid.UUID,
    user_id: uuid.UUID,
    title: str | None,
) -> Conversation:
    conversation = Conversation(company_id=company_id, user_id=user_id, title=title)
    session.add(conversation)
    session.flush()
    return conversation


def list_for_user(
    session: Session,
    *,
    company_id: uuid.UUID,
    user_id: uuid.UUID,
    limit: int,
    offset: int,
) -> tuple[list[Conversation], int]:
    conditions = [
        Conversation.company_id == company_id,
        Conversation.user_id == user_id,
    ]
    stmt = (
        select(Conversation)
        .where(*conditions)
        .order_by(Conversation.created_at.desc(), Conversation.id.asc())
    )
    total = session.execute(
        select(func.count()).select_from(stmt.subquery())
    ).scalar_one()
    items = list(session.execute(stmt.limit(limit).offset(offset)).scalars().all())
    return items, total


def list_for_company(
    session: Session,
    *,
    company_id: uuid.UUID,
    limit: int,
    offset: int,
) -> tuple[list[Conversation], int]:
    stmt = (
        select(Conversation)
        .where(Conversation.company_id == company_id)
        .order_by(Conversation.created_at.desc(), Conversation.id.asc())
    )
    total = session.execute(
        select(func.count()).select_from(stmt.subquery())
    ).scalar_one()
    items = list(session.execute(stmt.limit(limit).offset(offset)).scalars().all())
    return items, total


def delete(session: Session, *, record: Conversation) -> None:
    session.delete(record)
    session.flush()
