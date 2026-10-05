"""Document DTOs. Storage keys never leave the backend (tenant internals)."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

DocumentStatusFilter = Literal["uploaded", "processing", "indexed", "failed"]


class DocumentRead(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    title: str
    original_filename: str
    media_type: str
    file_size: int
    sha256_hash: str
    fiscal_year: int | None
    status: str
    page_count: int | None
    ingestion_error: str | None
    ingestion_error_code: str | None
    # Vector/index readiness (Phase 5): separate from `status` (pages-ready).
    embedding_status: str
    embedding_model: str | None
    chunk_count: int
    created_at: datetime
    updated_at: datetime


class UploadResponse(BaseModel):
    """201 on first ingest, 200 when the file deduped to an existing row."""

    document: DocumentRead
    duplicate: bool


class PageRead(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    company_id: uuid.UUID
    page_number: int
    page_type: str
    extracted_text: str
    extraction_status: str
    extraction_error: str | None
    text_char_count: int
    has_tables: bool
    has_images: bool
    table_count: int
    tables: list[dict[str, Any]] | None
    created_at: datetime
    updated_at: datetime
