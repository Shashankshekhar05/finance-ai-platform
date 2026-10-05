"""AI answer DTOs: closed statuses, validated inputs, safe citations."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.calculation import CalculationRequest
from app.schemas.retrieval import SearchRequest

AnswerStatus = Literal["grounded", "insufficient_evidence", "citation_invalid"]


class AnswerRequest(BaseModel):
    """Controlled input: a question plus allowlisted backend evidence specs.

    The client NEVER sends evidence itself — only specs the backend resolves
    through tenant-scoped services. At least one spec is required.
    """

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=2000)
    calculation: CalculationRequest | None = None
    retrieval: SearchRequest | None = None

    @model_validator(mode="after")
    def _needs_evidence_source(self) -> "AnswerRequest":
        if self.calculation is None and self.retrieval is None:
            raise ValueError("at least one of calculation or retrieval is required.")
        return self


class Citation(BaseModel):
    evidence_id: str
    source_type: str
    document_title: str | None = None
    page_number: int | None = None
    chunk_id: str | None = None
    dataset: str | None = None
    operation: str | None = None


class AnswerResponse(BaseModel):
    status: AnswerStatus
    answer: str
    citations: list[Citation] = []
