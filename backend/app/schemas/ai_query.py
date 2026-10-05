"""Query request/plan schemas for POST /ai/query.

The client sends a question plus OPTIONAL controlled specs. Specs reuse the
existing validated request models (CalculationRequest, SearchRequest);
StructuredQuerySpec is new but equally closed (dataset enum, validated
filters, allowlisted sort, bounded paging). No company_id, no SQL, no raw
expressions anywhere — tenant scope comes only from the auth context.
"""

from typing import Literal

import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.calculation import CalculationRequest, Dataset, Filters
from app.schemas.retrieval import SearchRequest

RouteType = Literal["calculation", "sql", "rag", "hybrid", "clarify"]
ExplicitMode = Literal["calculation", "sql", "rag", "hybrid"]

StructuredSort = Literal["record_date", "occurred_at", "amount", "created_at"]
SortOrder = Literal["asc", "desc"]


class StructuredQuerySpec(BaseModel):
    """Controlled list-query spec: dataset + validated filters + paging."""

    model_config = ConfigDict(extra="forbid")

    dataset: Dataset = Dataset.revenue
    filters: Filters = Filters()
    sort: StructuredSort = "record_date"
    order: SortOrder = "desc"
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=2000)
    mode: ExplicitMode | None = None
    calculation: CalculationRequest | None = None
    retrieval: SearchRequest | None = None
    structured_query: StructuredQuerySpec | None = None
    # Optional thread to ask within. Scope is re-validated per request from
    # the auth context; omitted means stateless (no rows touched).
    conversation_id: uuid.UUID | None = None


class RoutePlan(BaseModel):
    """Typed router output: route + executable backend operations."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    route_type: RouteType
    reason: str
    calculation: CalculationRequest | None = None
    retrieval: SearchRequest | None = None
    structured_query: StructuredQuerySpec | None = None
    clarification: str | None = None


class QueryDebug(BaseModel):
    """Deterministic routing introspection (no secrets, no DB)."""

    route_type: RouteType
    reason: str
    clarification: str | None = None
