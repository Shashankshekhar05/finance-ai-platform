"""Router unit tests: pure, deterministic, no DB, no provider.

Locks the routing contract: matrices per route, precedence, explicit mode,
clarify outcomes, and 100× repeat determinism.
"""

from app.schemas.calculation import Dataset, Operation
from app.services.router import describe_route, route_question

CALC = "calculation"
SQL = "sql"
RAG = "rag"
HYBRID = "hybrid"
CLARIFY = "clarify"


def _route(question: str, mode=None) -> str:
    return route_question(question, mode).route_type


def test_calculation_matrix() -> None:
    cases = [
        "What was total revenue in FY2025?",
        "What is the average expense in Q4 2025?",
        "How many transactions happened in March?",
        "What was the minimum revenue?",
        "What was the maximum expense in FY2025?",
        "What was revenue growth in FY2025 vs FY2024?",
        "Show me the variance of expenses FY2025 vs FY2024.",
        "What is the margin?",
        "Compare revenue and expenses.",
        "What was the profit in FY2025?",
    ]
    for question in cases:
        assert _route(question) == CALC, question


def test_sql_matrix() -> None:
    cases = [
        "What was revenue in FY2025?",
        "Show revenue by region in FY2025.",
        "List transactions in March.",
        "Show expenses by category.",
        "List revenue.",
    ]
    for question in cases:
        assert _route(question) == SQL, question


def test_rag_matrix() -> None:
    cases = [
        "What did management say about future growth?",
        "According to the annual report, what is the policy?",
        "Which page states the dividend?",
        "Explain the accounting policy.",
        "What does the report say about revenue?",
        "Describe the disclosure on page 4.",
    ]
    for question in cases:
        assert _route(question) == RAG, question


def test_hybrid_matrix() -> None:
    cases = [
        "Why did revenue increase in FY2025?",
        "Explain the reason for the revenue increase in FY2025.",
        "What caused the expense increase in FY2025?",
        "Compare revenue growth and explain the reason from the report.",
        "Revenue increased significantly. Why?",
        "Why is the margin lower than last year according to the report?",
    ]
    for question in cases:
        assert _route(question) == HYBRID, question


def test_precedence_hybrid_beats_bare_calculation() -> None:
    plan = route_question("Why did revenue increase in FY2025?")
    assert plan.route_type == HYBRID
    assert plan.calculation is not None and plan.retrieval is not None


def test_precedence_framing_keeps_narrative_on_rag() -> None:
    assert _route("What was total revenue in FY2025 according to the report?") == CALC
    assert _route("What was total revenue according to the report?") == RAG
    assert _route("What did the report say the total was?") == RAG


def test_explicit_mode() -> None:
    assert _route("Anything at all about revenue?", mode="sql") == SQL
    assert _route("Anything at all?", mode="rag") == RAG
    plan = route_question("Revenue numbers.", mode="calculation")
    assert plan.route_type == CALC and plan.reason == "explicit_mode"
    plan = route_question("Revenue numbers.", mode="hybrid")
    assert plan.route_type == HYBRID and plan.retrieval is not None


def test_ambiguous_clarifies() -> None:
    cases = [
        "Tell me stuff.",
        "Hello there.",
        "Show me the money.",
        "What was the total?",
        "What was the YoY revenue growth?",
        "Revenue numbers please.",
    ]
    for question in cases:
        plan = route_question(question)
        assert plan.route_type == CLARIFY, question
        assert plan.clarification, question
        assert plan.calculation is None and plan.retrieval is None


def test_derived_specs_are_executable() -> None:
    plan = route_question("What was total revenue in FY2025 by region?")
    assert plan.route_type == CALC
    assert plan.calculation is not None
    assert plan.calculation.filters.fiscal_year == 2025
    assert plan.calculation.group_by == ["region"]

    plan = route_question("Why did revenue increase in FY2025?")
    assert plan.calculation is not None
    assert plan.calculation.current_period is not None
    assert plan.calculation.current_period.fiscal_year == 2025
    # Single year: comparison auto-fills to previous FY at execution time.
    assert plan.calculation.comparison_period is None
    assert plan.retrieval is not None
    assert "increase" in plan.retrieval.query.lower()


def test_hybrid_fallback_sum_without_period() -> None:
    plan = route_question("Revenue increased significantly. Why?")
    assert plan.route_type == HYBRID
    assert plan.calculation is not None
    assert plan.calculation.operation == Operation.sum
    assert plan.calculation.dataset == Dataset.revenue


def test_determinism_100_repeats() -> None:
    questions = [
        "What was revenue in FY2025?",
        "Why did revenue increase in FY2025?",
        "According to the report, what is the policy?",
        "Show expenses by category in Q1 2025.",
        "Tell me stuff.",
        "Compare revenue and expenses.",
    ]
    for question in questions:
        first = route_question(question)
        for _ in range(100):
            assert route_question(question) == first, question


def test_describe_route_stable() -> None:
    assert describe_route(route_question("List revenue.")) == {
        "route_type": SQL,
        "reason": "structured_intent",
        "clarification": None,
    }
