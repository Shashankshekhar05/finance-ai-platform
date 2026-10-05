"""Retrieval routes: evidence search + explicit vector indexing.

- POST /documents/search (viewer+): embed query → tenant-first pgvector
  Top-K → bounded evidence. No LLM, no answer synthesis.
- POST /documents/{id}/index (analyst+): chunk + batch-embed + persist
  vectors (idempotent delete/rebuild). Upload stays pages-only so it never
  pays model-load latency; indexing is explicit and retryable.
"""

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_settings, require_analyst, require_viewer
from app.schemas.retrieval import IndexSummary, SearchRequest, SearchResponse
from app.services import index_service, search_service
from app.services.tenancy import TenantContext

router = APIRouter(tags=["retrieval"])


@router.post("/documents/search", response_model=SearchResponse)
def search_documents(
    payload: SearchRequest,
    ctx: TenantContext = Depends(require_viewer),
    session: Session = Depends(get_db),
) -> SearchResponse:
    return search_service.search_evidence(
        session,
        company_id=ctx.company_id,
        query=payload.query,
        top_k=payload.top_k,
        document_id=payload.document_id,
        fiscal_year=payload.fiscal_year,
        page_number=payload.page_number,
        settings=get_settings(),
    )


@router.post(
    "/documents/{document_id}/index",
    response_model=IndexSummary,
    status_code=status.HTTP_200_OK,
)
def index_document(
    document_id: uuid.UUID,
    ctx: TenantContext = Depends(require_analyst),
    session: Session = Depends(get_db),
) -> IndexSummary:
    summary = index_service.index_document(
        session,
        company_id=ctx.company_id,
        document_id=document_id,
        settings=get_settings(),
    )
    return IndexSummary(**summary)
