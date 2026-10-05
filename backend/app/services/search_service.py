"""Evidence retrieval: embed the query → tenant-first pgvector Top-K.

Output is EVIDENCE (chunks + provenance + scores), never an answer — the
pipeline stops here by Phase 5 design. Score conversion is explicit:
`score = 1 - cosine_distance` (lower distance ranks first). Query text is
logged truncated (≤80 chars): it may carry sensitive financial content.
"""

import logging
import time
import uuid

from fastapi import status
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import raise_api_error
from app.repositories import chunk_repository
from app.schemas.retrieval import SearchHit, SearchResponse
from app.services import embeddings as embedding_module

logger = logging.getLogger(__name__)


def search_evidence(
    session: Session,
    *,
    company_id: uuid.UUID,
    query: str,
    top_k: int | None,
    document_id: uuid.UUID | None,
    fiscal_year: int | None,
    page_number: int | None,
    settings: Settings,
    embedding_service: embedding_module.EmbeddingService | None = None,
) -> SearchResponse:
    started = time.perf_counter()
    limit = settings.rag_top_k if top_k is None else top_k
    if limit < 1 or limit > settings.rag_max_top_k:
        raise raise_api_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "validation_error")
    service = embedding_service or embedding_module.get_embedding_service(settings)
    query_vector = service.embed_query(query)
    threshold = settings.rag_similarity_threshold
    max_distance = (1.0 - threshold) if threshold > 0 else None
    hits = chunk_repository.search(
        session,
        company_id=company_id,
        query_embedding=query_vector,
        top_k=limit,
        max_distance=max_distance,
        document_id=document_id,
        fiscal_year=fiscal_year,
        page_number=page_number,
    )
    duration_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "retrieval company_id=%s results=%s top_k=%s duration_ms=%s query=%.80s",
        company_id,
        len(hits),
        limit,
        duration_ms,
        query,
    )
    return SearchResponse(
        results=[
            SearchHit(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                document_title=title,
                page_number=chunk.page_number,
                chunk_index=chunk.chunk_index,
                chunk_type=chunk.chunk_type.value,
                text=chunk.text,
                score=1.0 - distance,
            )
            for chunk, title, distance in hits
        ],
    )
