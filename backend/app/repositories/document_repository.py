"""Document persistence. Company-scoped on every path; flush, never commit."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.document import Document, DocumentStatus


def get(
    session: Session, *, company_id: uuid.UUID, document_id: uuid.UUID
) -> Document | None:
    return session.execute(
        select(Document).where(
            Document.id == document_id, Document.company_id == company_id
        )
    ).scalar_one_or_none()


def get_by_sha256(
    session: Session, *, company_id: uuid.UUID, sha256_hash: str
) -> Document | None:
    return session.execute(
        select(Document).where(
            Document.company_id == company_id, Document.sha256_hash == sha256_hash
        )
    ).scalar_one_or_none()


def create(
    session: Session,
    *,
    document_id: uuid.UUID,
    company_id: uuid.UUID,
    title: str,
    original_filename: str,
    media_type: str,
    file_size: int,
    sha256_hash: str,
    storage_key: str,
    fiscal_year: int | None,
    status: DocumentStatus,
) -> Document:
    document = Document(
        id=document_id,
        company_id=company_id,
        title=title,
        original_filename=original_filename,
        media_type=media_type,
        file_size=file_size,
        sha256_hash=sha256_hash,
        storage_key=storage_key,
        fiscal_year=fiscal_year,
        status=status,
    )
    session.add(document)
    session.flush()
    return document


def list_paged(
    session: Session,
    *,
    company_id: uuid.UUID,
    status: DocumentStatus | None,
    limit: int,
    offset: int,
) -> tuple[list[Document], int]:
    conditions = [Document.company_id == company_id]
    if status is not None:
        conditions.append(Document.status == status)
    stmt = (
        select(Document)
        .where(*conditions)
        .order_by(Document.created_at.desc(), Document.id.asc())
    )
    total = session.execute(
        select(func.count()).select_from(stmt.subquery())
    ).scalar_one()
    items = list(session.execute(stmt.limit(limit).offset(offset)).scalars().all())
    return items, total
