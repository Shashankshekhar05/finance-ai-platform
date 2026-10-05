"""Deterministic query router: question text → typed RoutePlan. No LLM.

Precedence (documented, tested, stable):
  1. explicit mode (validated enum; specs provided or derived)
  2. hybrid: explanation marker (why/reason/cause/explain-change) AND a
     numeric/dataset signal — the combined intent is checked BEFORE bare
     calculation so "Why did revenue increase?" does not collapse to a
     number. Calculation-intent matching itself excludes explanation-framed
     questions, so the order is both explicit and example-consistent.
  3. calculation: pure numeric intent (op + dataset derivable from text).
     Document-framed questions stay narrative UNLESS they name both a
     dataset and a fiscal year (then the figure is authoritative-structured).
  4. sql: dataset + list/group/year framing ("show/list/by <dim>/FY"),
     never document-framed (explicit report requests stay on RAG).
  5. rag: document/report/policy/page signals
  6. clarify: anything unsafe to represent (no intent, no dataset, no
     period for comparisons, invalid group dim, multi-dataset ambiguity)

The router NEVER touches the database, the network, randomness, or time:
same input → same plan, always. Unknown vocabulary falls through to
clarify rather than guessing. Document text never reaches the router
(it runs before retrieval), so injections cannot steer routing.
"""

import re

from app.schemas.ai_query import ExplicitMode, RoutePlan
from app.schemas.calculation import (
    CalculationRequest,
    Dataset,
    Filters,
    Operation,
    Period,
)
from app.schemas.retrieval import SearchRequest
from app.schemas.ai_query import StructuredQuerySpec

_WORD = r"\b{}\b"

_EXPLAIN = ("why", "reason", "reasons", "cause", "caused", "causes")
_RAG_HINTS = (
    "according to",
    "report",
    "reports",
    "policy",
    "policies",
    "disclosure",
    "disclosures",
    "describe",
    "document",
    "documents",
    "page",
    "section",
    "stated",
    "says",
    "say",
)
_SQL_VERBS = ("list", "show")
_GROUP_DIMS = ("region", "segment", "category", "department")

# Per-dataset groupable dimensions (mirrors calculation_repository groups).
_CALC_GROUPS: dict[Dataset, frozenset[str]] = {
    Dataset.revenue: frozenset(
        {"region", "segment", "category", "fiscal_year", "fiscal_quarter"}
    ),
    Dataset.expense: frozenset(
        {"category", "department", "region", "fiscal_year", "fiscal_quarter"}
    ),
    Dataset.transaction: frozenset({"category", "account", "transaction_type"}),
}


def _has(text: str, word: str) -> bool:
    return re.search(_WORD.format(re.escape(word)), text) is not None


def _matches(text: str, pattern: str) -> bool:
    return re.search(pattern, text) is not None


_CALC_OPS: tuple[tuple[str, Operation], ...] = (
    # Stem patterns (not bare words): morphological variants must match.
    # First pattern wins; order is part of the deterministic contract.
    (
        r"\bgrowth(?:_rate| rate)?\b|\bgrew\b|\bgrows\b|\bgrowing\b",
        Operation.growth_rate,
    ),
    (r"\bmargin\w*\b", Operation.margin),
    (r"\bvariance\w*\b", Operation.variance),
    (r"\baverages?\b|\bavg\b", Operation.average),
    (r"\bminimum\b|\bminima\b|\bmin\b", Operation.minimum),
    (r"\bmaximum\b|\bmaxima\b|\bmax\b", Operation.maximum),
    (r"\btotals?\b|\bsums?\b", Operation.sum),
    (r"\bcounts?\b|\bhow many\b", Operation.count),
    (r"\bprofits?\b", Operation.margin),
    (r"\bpercent(?:age)?s?\b", Operation.margin),
    (r"\bcompar(?:e|ed|ing|ison)\b", Operation.variance),
    (r"\bchang(?:e|ed|es|ing)\b", Operation.growth_rate),
    (r"\bincreas(?:e|ed|es|ing)\b", Operation.growth_rate),
    (r"\bdecreas(?:e|ed|es|ing)\b", Operation.growth_rate),
)

_DATASETS: tuple[tuple[str, Dataset], ...] = (
    (r"\brevenues?\b", Dataset.revenue),
    (r"\bexpenses?\b|\bexpenditure\b|\bcosts?\b", Dataset.expense),
    (r"\btransactions?\b", Dataset.transaction),
)

_CHANGE_WORDS = (
    r"\bincreas(?:e|ed|es|ing)\b",
    r"\bdecreas(?:e|ed|es|ing)\b",
    r"\bchang(?:e|ed|es|ing)\b",
    r"\bgrowth\b|\bgrew\b|\bgrows\b",
    r"\bhigher\b",
    r"\blower\b",
)


def _extract_years(text: str) -> list[int]:
    years: list[int] = []
    for match in re.finditer(r"\bfy\s?(\d{4})\b", text):
        years.append(int(match.group(1)))
    for match in re.finditer(r"\bfiscal\s*(?:year\s*)?(\d{4})\b", text):
        years.append(int(match.group(1)))
    for match in re.finditer(r"\b((?:19|20)\d{2})\b", text):
        years.append(int(match.group(1)))
    return sorted({year for year in years if 1900 <= year <= 2100})


def _extract_quarter(text: str) -> int | None:
    match = re.search(r"\bq([1-4])\b", text)
    return int(match.group(1)) if match else None


def _extract_group_dims(text: str) -> list[str]:
    return [dim for dim in _GROUP_DIMS if re.search(rf"\bby\s+{dim}\b", text)]


def _find_dataset(text: str) -> Dataset | None:
    found = [dataset for pattern, dataset in _DATASETS if _matches(text, pattern)]
    unique = sorted(set(found), key=lambda d: d.value)
    return unique[0] if len(unique) == 1 else None


def _carry_dataset_word(current: str, context: str | None) -> str:
    """Follow-up helper: if the current question names no dataset but the
    previous user message named exactly one, prepend that dataset word so
    routing sees it. Only the dataset word carries forward — periods and
    operations always come from the current question alone (never invent
    a fiscal scope the user did not state). Pure function of the texts."""
    if not context:
        return current
    if _find_dataset(current) is not None or _needs_dataset_first(current):
        return current
    carried = _find_dataset(context.strip().lower())
    if carried is None:
        return current
    return f"{carried.value} {current}"


def _find_operation(text: str) -> Operation | None:
    for pattern, operation in _CALC_OPS:
        if _matches(text, pattern):
            return operation
    return None


def _has_explain_framing(text: str) -> bool:
    if any(_has(text, word) for word in _EXPLAIN):
        return True
    # "explain X" only counts when X is change-like, not document-like.
    return _has(text, "explain") and any(_matches(text, p) for p in _CHANGE_WORDS)


def _has_calc_signal(text: str) -> bool:
    if _find_operation(text) is not None:
        return True
    return _find_dataset(text) is not None and any(
        _matches(text, pattern) for pattern in _CHANGE_WORDS
    )


def _has_rag_framing(text: str) -> bool:
    """Broad document-framing test (report/says/policy/page/...). Used to
    keep narrative questions on RAG even when they name figures."""
    return _has_rag_signal(text)


def _has_sql_signal(text: str, dataset: Dataset | None) -> bool:
    if dataset is None:
        return False
    if _has_rag_framing(text):
        # Explicit document framing wins: the user asked the REPORT, not the table.
        return False
    if any(_has(text, verb) for verb in _SQL_VERBS):
        return True
    if _extract_group_dims(text):
        return True
    # Bare fact lookup over structured data ("What was revenue in FY2025?").
    return bool(_extract_years(text))


def _has_rag_signal(text: str) -> bool:
    return any(hint in text for hint in _RAG_HINTS)


def _clarify(reason: str, detail: str) -> RoutePlan:
    return RoutePlan(route_type="clarify", reason=reason, clarification=detail)


def _calc_request(
    dataset: Dataset, operation: Operation, text: str
) -> CalculationRequest | None:
    """Derive executable calc spec; None when unsafe (never invent)."""
    years = _extract_years(text)
    quarter = _extract_quarter(text)
    filters = Filters()
    group_by: list[str] = []
    for dim in _extract_group_dims(text):
        if dim not in _CALC_GROUPS[dataset]:
            return None
        group_by.append(dim)
    if operation in (Operation.growth_rate, Operation.variance):
        if not years:
            return None
        current = Period(fiscal_year=max(years), quarter=quarter)
        rest = [y for y in years if y != max(years)]
        comparison = Period(fiscal_year=max(rest), quarter=quarter) if rest else None
        return CalculationRequest(
            dataset=dataset,
            operation=operation,
            filters=filters,
            group_by=group_by,
            current_period=current,
            comparison_period=comparison,
        )
    if operation == Operation.margin:
        if years:
            filters = Filters(fiscal_year=max(years), quarter=quarter)
        return CalculationRequest(
            dataset=dataset, operation=operation, filters=filters, group_by=group_by
        )
    if years:
        filters = Filters(fiscal_year=max(years), quarter=quarter)
    return CalculationRequest(
        dataset=dataset, operation=operation, filters=filters, group_by=group_by
    )


def _needs_dataset_first(text: str) -> bool:
    """True when the question names two different datasets (ambiguous)."""
    found = {dataset for pattern, dataset in _DATASETS if _matches(text, pattern)}
    return len(found) > 1


def _retrieval_request(question: str, text: str) -> SearchRequest:
    years = _extract_years(text)
    return SearchRequest(
        query=question.strip(),
        fiscal_year=max(years) if len(years) == 1 else None,
    )


def _structured_spec(dataset: Dataset, text: str) -> StructuredQuerySpec:
    years = _extract_years(text)
    filters = Filters(fiscal_year=max(years)) if len(years) == 1 else Filters()
    return StructuredQuerySpec(dataset=dataset, filters=filters)


def route_question(
    question: str, mode: ExplicitMode | None = None, *, context: str | None = None
) -> RoutePlan:
    """Classify + derive executable specs. Pure function of the text.

    `context` is the previous user message (or None): only its dataset word
    may carry forward into routing; the asked question is never rewritten.
    """
    text = question.strip().lower()
    if not text:
        return _clarify("clarify:empty", "Empty question.")
    text = _carry_dataset_word(text, context)

    dataset = _find_dataset(text)
    operation = _find_operation(text)
    explain = _has_explain_framing(text)

    if mode is not None:
        return _explicit_route(mode, question, text, dataset, operation, explain)

    # Hybrid before bare calculation: explanation + numeric signal together.
    if explain and (operation is not None or _has_calc_signal(text)):
        target = dataset
        op = operation
        if target is None:
            if op == Operation.margin or not _needs_dataset_first(text):
                if op != Operation.margin:
                    return _clarify(
                        "clarify:missing_dataset", "Hybrid needs one dataset."
                    )
                target = Dataset.revenue  # margin implies its own revenue leg
            else:
                # revenue-vs-expense comparison phrasing → margin leg.
                target, op = Dataset.revenue, Operation.margin
        assert target is not None and op is not None
        spec = _calc_request(target, op, text)
        if spec is None:
            if op in (Operation.growth_rate, Operation.variance) and not _extract_years(
                text
            ):
                # No period derivable: fall back to an unfiltered total so the
                # hybrid still carries an honest numeric anchor; the retrieval
                # leg carries the explanation. Never invents a period.
                spec = CalculationRequest(dataset=target, operation=Operation.sum)
            else:
                return _clarify(
                    "clarify:missing_period",
                    "Hybrid needs an explicit fiscal period for the numeric leg.",
                )
        return RoutePlan(
            route_type="hybrid",
            reason="hybrid_intent",
            calculation=spec,
            retrieval=_retrieval_request(question, text),
        )

    # Document-framed questions stay narrative unless they name a dataset
    # AND a fiscal year (then the figure is authoritative-structured).
    framed_vague = _has_rag_framing(text) and not (
        dataset is not None and _extract_years(text)
    )
    if operation is not None and not explain and not framed_vague:
        if dataset is None:
            # compare + revenue&expense phrasing → margin without a dataset word.
            if operation == Operation.variance and _needs_dataset_first(text):
                spec = _calc_request(Dataset.revenue, Operation.margin, text)
                if spec is None:
                    return _clarify("clarify:missing_period", "Need a fiscal period.")
                return RoutePlan(
                    route_type="calculation",
                    reason="calculation_intent",
                    calculation=spec,
                )
            # margin implies its own revenue-vs-expense leg.
            if operation == Operation.margin and not _needs_dataset_first(text):
                spec = _calc_request(Dataset.revenue, Operation.margin, text)
                if spec is None:
                    return _clarify("clarify:missing_period", "Need a fiscal period.")
                return RoutePlan(
                    route_type="calculation",
                    reason="calculation_intent",
                    calculation=spec,
                )
            return _clarify("clarify:missing_dataset", "Calculation needs a dataset.")
        spec = _calc_request(dataset, operation, text)
        if spec is None:
            return _clarify(
                "clarify:missing_period",
                "Calculation needs an explicit fiscal period or valid grouping.",
            )
        return RoutePlan(
            route_type="calculation", reason="calculation_intent", calculation=spec
        )

    if _has_sql_signal(text, dataset):
        assert dataset is not None
        return RoutePlan(
            route_type="sql",
            reason="structured_intent",
            structured_query=_structured_spec(dataset, text),
        )

    if _has_rag_signal(text):
        return RoutePlan(
            route_type="rag",
            reason="rag_intent",
            retrieval=_retrieval_request(question, text),
        )

    return _clarify("clarify:no_intent", "Could not determine a safe route.")


def _explicit_route(
    mode: ExplicitMode,
    question: str,
    text: str,
    dataset: Dataset | None,
    operation: Operation | None,
    explain: bool,
) -> RoutePlan:
    if mode == "rag":
        return RoutePlan(
            route_type="rag",
            reason="explicit_mode",
            retrieval=_retrieval_request(question, text),
        )
    if mode == "sql":
        if dataset is None:
            return _clarify("clarify:missing_dataset", "Explicit SQL needs a dataset.")
        return RoutePlan(
            route_type="sql",
            reason="explicit_mode",
            structured_query=_structured_spec(dataset, text),
        )
    # calculation / hybrid need a dataset + operation; margin implies revenue.
    target = dataset
    op = operation
    if target is None:
        if not _needs_dataset_first(text) and op != Operation.margin:
            return _clarify("clarify:missing_dataset", "Explicit mode needs a dataset.")
        target = Dataset.revenue
        if op in (None, Operation.variance):
            op = Operation.margin
    if op is None:
        op = Operation.growth_rate if mode == "hybrid" else Operation.sum
    spec = _calc_request(target, op, text)
    if spec is None:
        if mode == "hybrid" and op in (Operation.growth_rate, Operation.variance):
            # Same SUM-all fallback as inferred hybrid: honest numeric anchor.
            spec = CalculationRequest(dataset=target, operation=Operation.sum)
        else:
            return _clarify(
                "clarify:missing_period", "Explicit mode needs derivable parameters."
            )
    if mode == "calculation":
        return RoutePlan(
            route_type="calculation", reason="explicit_mode", calculation=spec
        )
    return RoutePlan(
        route_type="hybrid",
        reason="explicit_mode",
        calculation=spec,
        retrieval=_retrieval_request(question, text),
    )


def describe_route(plan: RoutePlan) -> dict[str, str | None]:
    """Stable introspection view for tests/logs (no secrets, no DB)."""
    return {
        "route_type": plan.route_type,
        "reason": plan.reason,
        "clarification": plan.clarification,
    }
