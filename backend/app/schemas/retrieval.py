"""Retrieval DTOs: bounded evidence in, no embeddings out, ever."""

import uuid

from pydantic import BaseModel, ConfigDict, Field


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=1000)
    top_k: int | None = Field(default=None, ge=1)
    document_id: uuid.UUID | None = None
    fiscal_year: int | None = Field(default=None, ge=1900, le=2100)
    page_number: int | None = Field(default=None, ge=1)


class SearchHit(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    page_number: int
    chunk_index: int
    chunk_type: str
    text: str
    # Cosine SIMILARITY (1 - distance). Higher is better. See search_service.
    score: float


class SearchResponse(BaseModel):
    results: list[SearchHit]


class IndexSummary(BaseModel):
    document_id: uuid.UUID
    embedding_status: str
    chunk_count: int
    page_count: int | None
    embedding_model: str | None
