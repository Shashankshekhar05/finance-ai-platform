"""Company persistence. Queries only."""

import uuid

from sqlalchemy.orm import Session

from app.models.company import Company


def get_by_id(session: Session, company_id: uuid.UUID) -> Company | None:
    return session.get(Company, company_id)


def create(session: Session, *, name: str) -> Company:
    company = Company(name=name)
    session.add(company)
    session.flush()
    return company
