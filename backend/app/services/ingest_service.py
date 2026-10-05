"""Document ingestion orchestration: validate → dedupe → store → extract → persist.

Transaction design (documented exception to one-scope-per-request, required
by status tracking — a single atomic scope cannot persist `failed` rows):
  1. Bytes validated (size → signature → openable → page cap) BEFORE any write.
  2. File stored via StorageService (orphan on later DB failure is accepted
     and documented; a cleanup job can reclaim unreferenced keys later).
  3. Txn 1: document row (`processing`) + commit.
  4. CPU-only extraction (no DB).
  5. Txn 2: page rows + document → `indexed` + commit.
  6. On extraction failure after txn 1: txn 2' marks the document `failed`
     with a typed code + safe message (retryable via `reprocess`).

Dedupe: same (company_id, sha256) never creates a second row — the existing
row returns with duplicate=True (a `failed` existing row is retried in
place). Only analyst+ reaches here (route guard); every read stays scoped.
"""

import hashlib
import logging
import uuid
from typing import NoReturn

from fastapi import status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import raise_api_error
from app.models.document import Document, DocumentStatus
from app.models.document_page import DocumentPage
from app.repositories import document_repository, page_repository
from app.schemas.document import DocumentRead, PageRead
from app.schemas.finance_shared import Page, Pagination
from app.services.pdf import (
    PagePayload,
    PdfValidationError,
    extract_pdf,
    validate_pdf_bytes,
)
from app.services.storage import StorageService, document_key

logger = logging.getLogger(__name__)

_VALIDATION_STATUS = {
    "file_too_large": status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
    "too_many_pages": status.HTTP_422_UNPROCESSABLE_ENTITY,
    "unsupported_media_type": status.HTTP_422_UNPROCESSABLE_ENTITY,
    "corrupt_document": status.HTTP_422_UNPROCESSABLE_ENTITY,
}


def _validation_error(exc: PdfValidationError) -> NoReturn:
    raise raise_api_error(_VALIDATION_STATUS.get(exc.code, 422), exc.code)


def _to_page_read(page: DocumentPage) -> PageRead:
    return PageRead(
        id=page.id,
        document_id=page.document_id,
        company_id=page.company_id,
        page_number=page.page_number,
        page_type=page.page_type.value,
        extracted_text=page.extracted_text,
        extraction_status=page.extraction_status.value,
        extraction_error=page.extraction_error,
        text_char_count=page.text_char_count,
        has_tables=page.has_tables,
        has_images=page.has_images,
        table_count=page.table_count,
        tables=page.tables,
        created_at=page.created_at,
        updated_at=page.updated_at,
    )


def _to_document_read(document: Document) -> DocumentRead:
    return DocumentRead(
        id=document.id,
        company_id=document.company_id,
        title=document.title,
        original_filename=document.original_filename,
        media_type=document.media_type,
        file_size=document.file_size,
        sha256_hash=document.sha256_hash,
        fiscal_year=document.fiscal_year,
        status=document.status.value,
        page_count=document.page_count,
        ingestion_error=document.ingestion_error,
        ingestion_error_code=document.ingestion_error_code,
        embedding_status=document.embedding_status,
        embedding_model=document.embedding_model,
        chunk_count=document.chunk_count or 0,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


def _store_pages(session: Session, *, document: Document, data: bytes) -> None:
    """Replace pages from fresh extraction, mark indexed. One commit."""
    for existing in page_repository.list_for_document(
        session, company_id=document.company_id, document_id=document.id
    ):
        session.delete(existing)
    session.flush()
    document.status = DocumentStatus.processing
    document.ingestion_error = None
    document.ingestion_error_code = None
    payload = extract_pdf(data)
    for page in payload.pages:
        _insert_page(session, document=document, page=page)
    document.status = DocumentStatus.indexed
    document.page_count = payload.page_count
    session.commit()


def _insert_page(session: Session, *, document: Document, page: PagePayload) -> None:
    from app.models.document_page import PageType

    page_repository.create(
        session,
        document_id=document.id,
        company_id=document.company_id,
        page_number=page.page_number,
        page_type=PageType(page.page_type),
        extracted_text=page.text,
        extraction_ok=page.extraction_ok,
        extraction_error=page.extraction_error,
        has_tables=page.has_tables,
        has_images=page.has_images,
        table_count=page.table_count,
        tables=list(page.tables) if page.tables else None,
    )


def _mark_failed(
    session: Session, *, document: Document, code: str, message: str
) -> None:
    document.status = DocumentStatus.failed
    document.ingestion_error = message
    document.ingestion_error_code = code
    session.commit()


def upload_and_ingest(
    session: Session,
    *,
    company_id: uuid.UUID,
    title: str,
    original_filename: str,
    media_type: str,
    data: bytes,
    fiscal_year: int | None,
    settings: Settings,
    storage: StorageService,
) -> tuple[DocumentRead, bool]:
    """Upload + ingest. Returns (document, duplicate). Raises envelope errors."""
    try:
        validate_pdf_bytes(
            data,
            max_bytes=settings.document_max_bytes,
            max_pages=settings.document_max_pages,
        )
    except PdfValidationError as exc:
        _validation_error(exc)

    sha256_hash = hashlib.sha256(data).hexdigest()
    existing = document_repository.get_by_sha256(
        session, company_id=company_id, sha256_hash=sha256_hash
    )
    if existing is not None:
        if existing.status == DocumentStatus.failed:
            # Retry in place: same row, fresh extraction, no duplicate row.
            return _retry_existing(
                session, document=existing, data=data, storage=storage
            )
        session.refresh(existing)
        return _to_document_read(existing), True

    document_id = uuid.uuid4()
    key = document_key(company_id=str(company_id), document_id=str(document_id))
    try:
        storage.put(key=key, data=data)
    except OSError:
        logger.exception("storage write failed company_id=%s", company_id)
        raise raise_api_error(status.HTTP_500_INTERNAL_SERVER_ERROR, "internal_error")

    try:
        document = document_repository.create(
            session,
            document_id=document_id,
            company_id=company_id,
            title=title,
            original_filename=original_filename,
            media_type=media_type,
            file_size=len(data),
            sha256_hash=sha256_hash,
            storage_key=key,
            fiscal_year=fiscal_year,
            status=DocumentStatus.processing,
        )
        session.commit()
    except IntegrityError:
        # Lost a dedupe race: another request stored the same file first.
        session.rollback()
        try:
            storage.delete(key=key)
        except OSError:
            pass
        existing = document_repository.get_by_sha256(
            session, company_id=company_id, sha256_hash=sha256_hash
        )
        if existing is None:  # pragma: no cover - defensive; constraint says present
            raise raise_api_error(status.HTTP_409_CONFLICT, "invalid_state")
        session.refresh(existing)
        return _to_document_read(existing), True

    try:
        _store_pages(session, document=document, data=data)
    except PdfValidationError as exc:
        session.rollback()
        _mark_failed(session, document=document, code=exc.code, message=str(exc))
        _validation_error(exc)
    except Exception:
        session.rollback()
        _mark_failed(
            session,
            document=document,
            code="extraction_failed",
            message="Extraction failed.",
        )
        raise
    logger.info(
        "document indexed document_id=%s company_id=%s pages=%s",
        document.id,
        company_id,
        document.page_count,
    )
    session.refresh(document)
    return _to_document_read(document), False


def _retry_existing(
    session: Session, *, document: Document, data: bytes, storage: StorageService
) -> tuple[DocumentRead, bool]:
    stored = storage.get(key=document.storage_key)
    if stored != data:  # pragma: no cover - same sha implies same bytes
        raise raise_api_error(status.HTTP_409_CONFLICT, "invalid_state")
    try:
        _store_pages(session, document=document, data=data)
    except PdfValidationError as exc:
        session.rollback()
        _mark_failed(session, document=document, code=exc.code, message=str(exc))
        _validation_error(exc)
    except Exception:
        session.rollback()
        _mark_failed(
            session,
            document=document,
            code="extraction_failed",
            message="Extraction failed.",
        )
        raise
    session.refresh(document)
    return _to_document_read(document), True


def reprocess(
    session: Session,
    *,
    company_id: uuid.UUID,
    document_id: uuid.UUID,
    settings: Settings,
    storage: StorageService,
) -> DocumentRead:
    """Retry extraction for a `failed` document. Anything else → 409."""
    document = document_repository.get(
        session, company_id=company_id, document_id=document_id
    )
    if document is None:
        raise raise_api_error(status.HTTP_404_NOT_FOUND, "not_found")
    if document.status != DocumentStatus.failed:
        raise raise_api_error(status.HTTP_409_CONFLICT, "invalid_state")
    try:
        data = storage.get(key=document.storage_key)
    except OSError:
        raise raise_api_error(status.HTTP_409_CONFLICT, "invalid_state")
    try:
        validate_pdf_bytes(
            data,
            max_bytes=settings.document_max_bytes,
            max_pages=settings.document_max_pages,
        )
    except PdfValidationError as exc:
        _validation_error(exc)
    _retry_existing(session, document=document, data=data, storage=storage)
    session.refresh(document)
    return _to_document_read(document)


def get_document(
    session: Session, *, company_id: uuid.UUID, document_id: uuid.UUID
) -> DocumentRead:
    document = document_repository.get(
        session, company_id=company_id, document_id=document_id
    )
    if document is None:
        raise raise_api_error(status.HTTP_404_NOT_FOUND, "not_found")
    return _to_document_read(document)


def list_documents(
    session: Session,
    *,
    company_id: uuid.UUID,
    status_filter: DocumentStatus | None,
    paging: Pagination,
) -> Page[DocumentRead]:
    items, total = document_repository.list_paged(
        session,
        company_id=company_id,
        status=status_filter,
        limit=paging.limit,
        offset=paging.offset,
    )
    return Page[DocumentRead](
        items=[_to_document_read(document) for document in items],
        total=total,
        limit=paging.limit,
        offset=paging.offset,
    )


def list_pages(
    session: Session, *, company_id: uuid.UUID, document_id: uuid.UUID
) -> list[PageRead]:
    if (
        document_repository.get(session, company_id=company_id, document_id=document_id)
        is None
    ):
        raise raise_api_error(status.HTTP_404_NOT_FOUND, "not_found")
    return [
        _to_page_read(page)
        for page in page_repository.list_for_document(
            session, company_id=company_id, document_id=document_id
        )
    ]
