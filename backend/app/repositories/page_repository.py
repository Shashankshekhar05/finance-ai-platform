"""Document-page persistence. Scoped by (company_id, document_id) always."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.document_page import DocumentPage, ExtractionStatus, PageType


def list_for_document(
    session: Session, *, company_id: uuid.UUID, document_id: uuid.UUID
) -> list[DocumentPage]:
    return list(
        session.execute(
            select(DocumentPage)
            .where(
                DocumentPage.document_id == document_id,
                DocumentPage.company_id == company_id,
            )
            .order_by(DocumentPage.page_number.asc())
        )
        .scalars()
        .all()
    )


def create(
    session: Session,
    *,
    document_id: uuid.UUID,
    company_id: uuid.UUID,
    page_number: int,
    page_type: PageType,
    extracted_text: str,
    extraction_ok: bool,
    extraction_error: str | None,
    has_tables: bool,
    has_images: bool,
    table_count: int,
    tables: list[dict] | None,
) -> DocumentPage:
    page = DocumentPage(
        document_id=document_id,
        company_id=company_id,
        page_number=page_number,
        page_type=page_type,
        extracted_text=extracted_text,
        extraction_status=(
            ExtractionStatus.ok if extraction_ok else ExtractionStatus.failed
        ),
        extraction_error=extraction_error,
        text_char_count=len(extracted_text),
        has_tables=has_tables,
        has_images=has_images,
        table_count=table_count,
        tables=tables,
    )
    session.add(page)
    session.flush()
    return page
