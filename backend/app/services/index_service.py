"""Document indexing: pages → deterministic chunks → batch embeddings → pgvector.

Flow (DATABASE_RULES.md §7A.4: prepare → embed → persist in bounded txns):
  1. Load scoped document (404 if foreign/missing); require pages-ready
     (`indexed`), else 409 — vectors never claim readiness over bad pages.
  2. Mark `embedding_status=indexing` (own commit: failure stays visible).
  3. Chunk in memory (pure, no DB) → batch-embed (CPU, no DB).
  4. ONE bounded transaction: delete stale chunks + insert fresh + mark
     `ready` (model, count). Failure → rollback → mark `failed`, re-raise.

Delete/rebuild (not upsert): chunk identity is positional per document, so
a rebuild converges exactly — no stale chunks, no version bookkeeping.
Visual-only/empty documents index to `ready` with zero chunks (nothing
meaningful exists to embed — recorded, not hidden).
"""

import logging
import time
import uuid

from fastapi import status
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import raise_api_error
from app.models.document import Document, DocumentStatus
from app.repositories import chunk_repository, document_repository
from app.services import embeddings as embedding_module
from app.services.chunking import PageInput, chunk_document_pages

logger = logging.getLogger(__name__)


def _to_inputs(document: Document) -> list[PageInput]:
    # Pages arrive ordered; chunk_index follows document order.
    return [
        PageInput(
            page_id=str(page.id),
            page_number=page.page_number,
            text=page.extracted_text or "",
            page_type=page.page_type.value,
            has_tables=page.has_tables,
            has_images=page.has_images,
            table_count=page.table_count,
            tables=tuple(page.tables or []),
        )
        for page in sorted(document.pages, key=lambda p: p.page_number)
    ]


def index_document(
    session: Session,
    *,
    company_id: uuid.UUID,
    document_id: uuid.UUID,
    settings: Settings,
    embedding_service: embedding_module.EmbeddingService | None = None,
) -> dict:
    started = time.perf_counter()
    document = document_repository.get(
        session, company_id=company_id, document_id=document_id
    )
    if document is None:
        raise raise_api_error(status.HTTP_404_NOT_FOUND, "not_found")
    if document.status != DocumentStatus.indexed:
        raise raise_api_error(status.HTTP_409_CONFLICT, "invalid_state")

    service = embedding_service or embedding_module.get_embedding_service(settings)
    document.embedding_status = "indexing"
    document.embedding_error = None
    session.commit()
    logger.info(
        "indexing started document_id=%s company_id=%s model=%s",
        document.id,
        company_id,
        service.model_name,
    )
    try:
        payloads = chunk_document_pages(
            _to_inputs(document),
            size=settings.rag_chunk_size,
            overlap=settings.rag_chunk_overlap,
        )
        vectors = service.embed_texts(
            [payload.text for payload in payloads], role="document"
        )
        chunk_repository.delete_for_document(
            session, company_id=company_id, document_id=document.id
        )
        rows = [
            {
                "company_id": company_id,
                "document_id": document.id,
                "page_id": uuid.UUID(payload.page_id),
                "page_number": payload.page_number,
                "chunk_index": payload.chunk_index,
                "text": payload.text,
                "text_char_count": payload.char_count,
                "token_count": payload.token_count,
                "chunk_type": payload.chunk_type,
                "chunk_metadata": payload.metadata,
                "embedding": vector,
                "embedding_model": service.model_name,
                "embedding_dimensions": settings.embedding_dimensions,
            }
            for payload, vector in zip(payloads, vectors)
        ]
        if rows:
            chunk_repository.insert_many(session, rows=rows)
        document.embedding_status = "ready"
        document.embedding_model = service.model_name
        document.chunk_count = len(rows)
        session.commit()
    except Exception:
        session.rollback()
        document.embedding_status = "failed"
        document.embedding_error = "Indexing failed."
        session.commit()
        raise
    duration_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "indexing finished document_id=%s company_id=%s chunks=%s duration_ms=%s",
        document.id,
        company_id,
        document.chunk_count,
        duration_ms,
    )
    session.refresh(document)
    return {
        "document_id": str(document.id),
        "embedding_status": document.embedding_status,
        "chunk_count": document.chunk_count,
        "page_count": document.page_count,
        "embedding_model": document.embedding_model,
    }
