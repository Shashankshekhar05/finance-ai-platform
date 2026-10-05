"""AI query orchestration: RoutePlan → existing services → AnswerService.

The orchestrator NEVER calculates, retrieves, or calls the LLM itself:
- router decides WHAT is needed (pure, no DB),
- existing services execute HOW (tenant-scoped, tested),
- AnswerService renders the grounded answer (single LLM call max).

Client-provided specs (validated Pydantic) override derived ones only
within the chosen route; anything route-irrelevant is ignored and logged.
Clarify plans answer WITHOUT any provider call.

Conversation threads (optional `conversation_id`) add bounded supporting
context and message persistence around the SAME pipeline: history never
enters routing as anything but a dataset-carryforward hint, and never
enters the prompt except inside the delimited conversation block.
"""

import logging
import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.schemas.ai import AnswerResponse
from app.schemas.ai_query import QueryRequest, RoutePlan
from app.schemas.calculation import Dataset, Filters
from app.schemas.expense import ExpenseFilter
from app.schemas.finance_shared import Pagination
from app.schemas.revenue import RevenueFilter
from app.schemas.transaction import TransactionFilter, TransactionType
from app.services import (
    answer_service,
    conversation_service,
    expense_service,
    revenue_service,
    transaction_service,
)
from app.services.evidence import EvidencePacket
from app.services.groq_client import GroqClient
from app.services.router import route_question
from app.services.tenancy import TenantContext

logger = logging.getLogger(__name__)

_CLARIFY_MESSAGE = (
    "I need a bit more detail to answer safely: "
    "{detail} Please ask about a specific dataset, period, or document."
)

# Generic Filters name -> per-dataset filter field (quarter renames included).
_FILTER_FIELDS: dict[Dataset, dict[str, str]] = {
    Dataset.revenue: {
        "fiscal_year": "fiscal_year",
        "quarter": "fiscal_quarter",
        "date_from": "date_from",
        "date_to": "date_to",
        "category": "category",
        "segment": "segment",
        "region": "region",
        "currency": "currency",
    },
    Dataset.expense: {
        "fiscal_year": "fiscal_year",
        "quarter": "fiscal_quarter",
        "date_from": "date_from",
        "date_to": "date_to",
        "category": "category",
        "department": "department",
        "region": "region",
        "currency": "currency",
    },
    Dataset.transaction: {
        "date_from": "date_from",
        "date_to": "date_to",
        "transaction_type": "type",
        "category": "category",
        "account": "account",
        "currency": "currency",
    },
}

# Sort allowlists per dataset (subset of each list endpoint's own literals).
_SORTS: dict[Dataset, frozenset[str]] = {
    Dataset.revenue: frozenset({"record_date", "amount", "created_at"}),
    Dataset.expense: frozenset({"record_date", "amount", "created_at"}),
    Dataset.transaction: frozenset({"occurred_at", "amount", "created_at"}),
}

_DEFAULT_SORT: dict[Dataset, str] = {
    Dataset.revenue: "record_date",
    Dataset.expense: "record_date",
    Dataset.transaction: "occurred_at",
}

# Row → evidence details (scalar, JSON-safe, money already strings).
_ROW_FIELDS: dict[Dataset, tuple[str, ...]] = {
    Dataset.revenue: (
        "amount",
        "currency",
        "record_date",
        "region",
        "segment",
        "category",
        "fiscal_year",
        "fiscal_quarter",
    ),
    Dataset.expense: (
        "amount",
        "currency",
        "record_date",
        "category",
        "department",
        "region",
        "vendor",
    ),
    Dataset.transaction: (
        "amount",
        "currency",
        "occurred_at",
        "type",
        "category",
        "account",
        "reference",
    ),
}


def _coerce_dates(dataset: Dataset, values: dict) -> dict:
    """DATE columns need dates; datetimes pass through for transactions."""
    if dataset is Dataset.transaction:
        return values
    coerced = dict(values)
    for key in ("date_from", "date_to"):
        value = coerced.get(key)
        if isinstance(value, datetime):
            coerced[key] = value.date()
    return coerced


def _build_typed_filters(dataset: Dataset, filters: Filters):  # type: ignore[no-untyped-def]
    provided = filters.model_dump(exclude_unset=True, exclude_none=True)
    mapping = _FILTER_FIELDS[dataset]
    values = {
        mapping[name]: value for name, value in provided.items() if name in mapping
    }
    values = _coerce_dates(dataset, values)
    if dataset is Dataset.revenue:
        return RevenueFilter(**values)
    if dataset is Dataset.expense:
        return ExpenseFilter(**values)
    enum_fix = dict(values)
    if isinstance(enum_fix.get("type"), str):
        enum_fix["type"] = TransactionType(enum_fix["type"])
    return TransactionFilter(**enum_fix)


def _list_rows(session: Session, *, company_id: uuid.UUID, spec) -> list:  # type: ignore[no-untyped-def]
    """Run the existing list service for a structured spec (read-only)."""
    from app.schemas.ai_query import StructuredQuerySpec

    assert isinstance(spec, StructuredQuerySpec)
    typed = _build_typed_filters(spec.dataset, spec.filters)
    sort = (
        spec.sort if spec.sort in _SORTS[spec.dataset] else _DEFAULT_SORT[spec.dataset]
    )
    typed = typed.model_copy(update={"sort": sort})
    paging = Pagination(limit=spec.limit, offset=spec.offset)
    if spec.dataset is Dataset.revenue:
        page = revenue_service.list_revenue(
            session,
            company_id=company_id,
            filters=typed,
            paging=paging,
            order=spec.order,
        )
    elif spec.dataset is Dataset.expense:
        page = expense_service.list_expenses(
            session,
            company_id=company_id,
            filters=typed,
            paging=paging,
            order=spec.order,
        )
    else:
        page = transaction_service.list_transactions(
            session,
            company_id=company_id,
            filters=typed,
            paging=paging,
            order=spec.order,
        )
    rows = []
    for item in page.items:
        details = {}
        for field_name in _ROW_FIELDS[spec.dataset]:
            value = getattr(item, field_name, None)
            details[field_name] = (
                value.value
                if isinstance(value, TransactionType)
                else (value.isoformat() if hasattr(value, "isoformat") else value)
            )
        rows.append((f"{spec.dataset.value} record", details, spec.dataset.value))
    return rows


def _resolve_plan(request: QueryRequest, context: str | None = None) -> RoutePlan:
    """Route from text, honoring caller specs. A provided spec for the
    selected (or mode-forced) route is used verbatim — already
    schema-validated, no derivation needed. Specs for other routes are
    ignored (documented); missing pieces derive from text or clarify."""
    mode = request.mode
    if mode is None:
        if request.calculation is not None and request.retrieval is not None:
            mode = "hybrid"
        elif request.calculation is not None:
            mode = "calculation"
        elif request.structured_query is not None:
            mode = "sql"
        elif request.retrieval is not None:
            mode = "rag"
    if mode == "sql" and request.structured_query is not None:
        return RoutePlan(
            route_type="sql",
            reason="explicit_spec",
            structured_query=request.structured_query,
        )
    if mode == "calculation" and request.calculation is not None:
        return RoutePlan(
            route_type="calculation",
            reason="explicit_spec",
            calculation=request.calculation,
        )
    if mode == "rag" and request.retrieval is not None:
        return RoutePlan(
            route_type="rag", reason="explicit_spec", retrieval=request.retrieval
        )
    if (
        mode == "hybrid"
        and request.calculation is not None
        and request.retrieval is not None
    ):
        return RoutePlan(
            route_type="hybrid",
            reason="explicit_spec",
            calculation=request.calculation,
            retrieval=request.retrieval,
        )
    plan = route_question(request.question, mode, context=context)
    if plan.route_type == "clarify":
        return plan
    updates = {}
    if request.calculation is not None and plan.route_type in (
        "calculation",
        "hybrid",
    ):
        updates["calculation"] = request.calculation
    if request.retrieval is not None and plan.route_type in ("rag", "hybrid"):
        updates["retrieval"] = request.retrieval
    if request.structured_query is not None and plan.route_type == "sql":
        updates["structured_query"] = request.structured_query
    if updates:
        plan = plan.model_copy(update=updates)
    return plan


def answer_query(
    session: Session,
    *,
    ctx: TenantContext,
    request: QueryRequest,
    settings: Settings,
    llm_client: GroqClient | None = None,
) -> AnswerResponse:
    """Execute a RoutePlan with existing services; one LLM call maximum.

    With `conversation_id`: validates thread access, persists the user
    question, routes with the previous user message as a dataset hint,
    answers with bounded history as supporting context, then persists the
    assistant reply. Provider failures leave the user message persisted and
    no assistant message (documented). Without it: legacy stateless path.
    """
    from app.models.conversation import MessageRole

    company_id = ctx.company_id
    history: list[tuple[str, str]] = []
    context_hint: str | None = None
    conversation_id = request.conversation_id
    if conversation_id is not None:
        history = conversation_service.get_context_window(
            session, ctx=ctx, conversation_id=conversation_id, settings=settings
        )
        # Dataset carryforward uses the most recent USER turn only.
        for role, content in reversed(history):
            if role == MessageRole.user.value:
                context_hint = content
                break
        conversation_service.append_message(
            session,
            ctx=ctx,
            conversation_id=conversation_id,
            role=MessageRole.user,
            content=request.question,
        )
    plan = _resolve_plan(request, context=context_hint)
    logger.info(
        "ai_query route=%s reason=%s company_id=%s conversation_id=%s",
        plan.route_type,
        plan.reason,
        company_id,
        conversation_id,
    )
    if plan.route_type == "clarify":
        response = AnswerResponse(
            status="insufficient_evidence",
            answer=_CLARIFY_MESSAGE.format(
                detail=plan.clarification or "Ambiguous question."
            ),
            citations=[],
        )
    elif plan.route_type == "sql":
        assert plan.structured_query is not None
        rows = _list_rows(session, company_id=company_id, spec=plan.structured_query)
        packet = EvidencePacket.build(
            data=rows,
            max_items=settings.ai_max_evidence_items,
            max_chars=settings.ai_max_evidence_chars,
        )
        response = answer_service.answer_question(
            session,
            company_id=company_id,
            question=request.question,
            settings=settings,
            llm_client=llm_client,
            packet=packet,
            history=history or None,
        )
    else:
        # calculation / rag / hybrid delegate execution to the answer service,
        # which resolves the same specs through the same tenant-scoped services.
        response = answer_service.answer_question(
            session,
            company_id=company_id,
            question=request.question,
            calculation=plan.calculation
            if plan.route_type in ("calculation", "hybrid")
            else None,
            retrieval=plan.retrieval if plan.route_type in ("rag", "hybrid") else None,
            settings=settings,
            llm_client=llm_client,
            history=history or None,
        )
    if conversation_id is not None:
        conversation_service.append_message(
            session,
            ctx=ctx,
            conversation_id=conversation_id,
            role=MessageRole.assistant,
            content=response.answer,
        )
    return response
