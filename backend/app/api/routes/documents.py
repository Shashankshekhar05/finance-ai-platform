"""Document routes. Thin: guards → one service call → typed DTO.

- POST /documents/upload (analyst+): multipart file + title + fiscal_year.
  201 first ingest, 200 `duplicate:true` when the bytes already exist.
- GET /documents (viewer+): paged, optional status filter.
- GET /documents/{id} (viewer+): metadata (pages via /pages).
- GET /documents/{id}/pages (viewer+): 1-based pages in order.
- POST /documents/{id}/reprocess (analyst+): retry a `failed` document.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import (
    get_db,
    get_settings,
    require_analyst,
    require_viewer,
)
from app.core.errors import raise_api_error
from app.models.document import DocumentStatus
from app.schemas.document import (
    DocumentRead,
    DocumentStatusFilter,
    PageRead,
    UploadResponse,
)
from app.schemas.finance_shared import Page, Pagination
from app.services import ingest_service
from app.services.storage import local_storage
from app.services.tenancy import TenantContext

router = APIRouter(tags=["documents"])

_STATUS_BY_FILTER: dict[str, DocumentStatus] = {
    "uploaded": DocumentStatus.uploaded,
    "processing": DocumentStatus.processing,
    "indexed": DocumentStatus.indexed,
    "failed": DocumentStatus.failed,
}


@router.post("/documents/upload", response_model=UploadResponse)
async def upload_document(
    response: Response,
    file: Annotated[UploadFile, File()],
    title: Annotated[str, Form(min_length=1, max_length=255)],
    fiscal_year: Annotated[int | None, Form(ge=1900, le=2100)] = None,
    ctx: TenantContext = Depends(require_analyst),
    session: Session = Depends(get_db),
) -> UploadResponse:
    settings = get_settings()
    # Bounded read: one byte past the cap proves over-limit without
    # loading an arbitrarily large body into memory.
    raw = await file.read(settings.document_max_bytes + 1)
    if len(raw) > settings.document_max_bytes:
        raise raise_api_error(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "file_too_large"
        )
    clean_title = title.strip()
    if not clean_title:
        raise raise_api_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "validation_error")
    document, duplicate = ingest_service.upload_and_ingest(
        session,
        company_id=ctx.company_id,
        title=clean_title,
        original_filename=(file.filename or "upload.pdf")[-255:],
        media_type=file.content_type or "application/octet-stream",
        data=bytes(raw),
        fiscal_year=fiscal_year,
        settings=settings,
        storage=local_storage(settings.document_storage_root),
    )
    response.status_code = status.HTTP_200_OK if duplicate else status.HTTP_201_CREATED
    return UploadResponse(document=document, duplicate=duplicate)


@router.get("/documents", response_model=Page[DocumentRead])
def list_documents(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    status: Annotated[DocumentStatusFilter | None, Query()] = None,
    ctx: TenantContext = Depends(require_viewer),
    session: Session = Depends(get_db),
) -> Page[DocumentRead]:
    return ingest_service.list_documents(
        session,
        company_id=ctx.company_id,
        status_filter=_STATUS_BY_FILTER[status] if status is not None else None,
        paging=Pagination(limit=limit, offset=offset),
    )


@router.get("/documents/{document_id}", response_model=DocumentRead)
def get_document(
    document_id: uuid.UUID,
    ctx: TenantContext = Depends(require_viewer),
    session: Session = Depends(get_db),
) -> DocumentRead:
    return ingest_service.get_document(
        session, company_id=ctx.company_id, document_id=document_id
    )


@router.get("/documents/{document_id}/pages", response_model=list[PageRead])
def list_document_pages(
    document_id: uuid.UUID,
    ctx: TenantContext = Depends(require_viewer),
    session: Session = Depends(get_db),
) -> list[PageRead]:
    return ingest_service.list_pages(
        session, company_id=ctx.company_id, document_id=document_id
    )


@router.post("/documents/{document_id}/reprocess", response_model=DocumentRead)
def reprocess_document(
    document_id: uuid.UUID,
    ctx: TenantContext = Depends(require_analyst),
    session: Session = Depends(get_db),
) -> DocumentRead:
    settings = get_settings()
    return ingest_service.reprocess(
        session,
        company_id=ctx.company_id,
        document_id=document_id,
        settings=settings,
        storage=local_storage(settings.document_storage_root),
    )
