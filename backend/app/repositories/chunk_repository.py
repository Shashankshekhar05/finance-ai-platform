"""Chunk persistence + tenant-first vector retrieval.

Every method is company-scoped — there is no unscoped chunk access path.
The similarity query filters `company_id` INSIDE SQL (never fetch-then-
filter in Python) and orders by cosine distance with chunk-id tiebreak.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.document_chunk import DocumentChunk


def insert_many(session: Session, *, rows: list[dict]) -> list[DocumentChunk]:
    chunks = [DocumentChunk(**row) for row in rows]
    session.add_all(chunks)
    session.flush()
    return chunks


def delete_for_document(
    session: Session, *, company_id: uuid.UUID, document_id: uuid.UUID
) -> int:
    existing = list(
        session.execute(
            select(DocumentChunk).where(
                DocumentChunk.company_id == company_id,
                DocumentChunk.document_id == document_id,
            )
        )
        .scalars()
        .all()
    )
    for chunk in existing:
        session.delete(chunk)
    session.flush()
    return len(existing)


def count_for_document(
    session: Session, *, company_id: uuid.UUID, document_id: uuid.UUID
) -> int:
    return session.execute(
        select(func.count())
        .select_from(DocumentChunk)
        .where(
            DocumentChunk.company_id == company_id,
            DocumentChunk.document_id == document_id,
        )
    ).scalar_one()


def get(
    session: Session, *, company_id: uuid.UUID, chunk_id: uuid.UUID
) -> DocumentChunk | None:
    return session.execute(
        select(DocumentChunk).where(
            DocumentChunk.id == chunk_id, DocumentChunk.company_id == company_id
        )
    ).scalar_one_or_none()


def search(
    session: Session,
    *,
    company_id: uuid.UUID,
    query_embedding: list[float],
    top_k: int,
    max_distance: float | None,
    document_id: uuid.UUID | None = None,
    fiscal_year: int | None = None,
    page_number: int | None = None,
) -> list[tuple[DocumentChunk, str, float]]:
    """Tenant-first cosine search. Returns (chunk, document_title, distance).

    Distance is pgvector `<=>` (lower is better); callers convert to
    similarity explicitly (score = 1 - distance). Ordering is deterministic:
    distance first, chunk id second.
    """
    distance = DocumentChunk.embedding.cosine_distance(query_embedding)
    stmt = (
        select(DocumentChunk, Document.title, distance.label("distance"))
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(DocumentChunk.company_id == company_id)
    )
    if max_distance is not None:
        stmt = stmt.where(
            DocumentChunk.embedding.cosine_distance(query_embedding) <= max_distance
        )
    if document_id is not None:
        stmt = stmt.where(DocumentChunk.document_id == document_id)
    if fiscal_year is not None:
        stmt = stmt.where(Document.fiscal_year == fiscal_year)
    if page_number is not None:
        stmt = stmt.where(DocumentChunk.page_number == page_number)
    stmt = stmt.order_by("distance", DocumentChunk.id.asc()).limit(top_k)
    return [
        (chunk, title, float(dist))
        for chunk, title, dist in session.execute(stmt).all()
    ]
