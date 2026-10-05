"""Membership persistence. Every method is company-scoped by construction."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user_role import Role, UserRole


def get_membership(
    session: Session, *, user_id: uuid.UUID, company_id: uuid.UUID
) -> UserRole | None:
    return session.execute(
        select(UserRole).where(
            UserRole.user_id == user_id, UserRole.company_id == company_id
        )
    ).scalar_one_or_none()


def list_for_user(session: Session, *, user_id: uuid.UUID) -> list[UserRole]:
    return list(
        session.execute(select(UserRole).where(UserRole.user_id == user_id))
        .scalars()
        .all()
    )


def create(
    session: Session, *, user_id: uuid.UUID, company_id: uuid.UUID, role: Role
) -> UserRole:
    membership = UserRole(user_id=user_id, company_id=company_id, role=role)
    session.add(membership)
    session.flush()
    return membership
