"""Calculation orchestration: validate → aggregate (SQL) → Decimal math → result.

Read-only: no commits, no writes, no model changes. Flow per request:
  1. Dataset-specific filter/group validation (unknown names → 422, never
     silently ignored).
  2. Scoped aggregation in PostgreSQL (sums/counts, never row hauling).
  3. Single-currency guard (mixed → 422, never silent addition).
  4. Pure Decimal math (calc_math) with explicit no-data/undefined states.

Provenance (dataset, operation, filters, scope, counts, timestamp) rides on
every result so a future LLM can explain without inventing anything.
"""

import logging
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import status
from sqlalchemy.orm import Session

from app.core.errors import raise_api_error
from app.repositories import calculation_repository as repo
from app.repositories.calculation_repository import DATASETS
from app.schemas.calculation import (
    CalculationRequest,
    CalculationResponse,
    ComparisonResult,
    Dataset,
    Filters,
    GroupedResult,
    GroupValue,
    MarginResult,
    Operation,
    Period,
    Provenance,
    SingleResult,
)
from app.services import calc_math

logger = logging.getLogger(__name__)

_SINGLE_OPS = {
    Operation.sum,
    Operation.count,
    Operation.average,
    Operation.minimum,
    Operation.maximum,
}
_MARGIN_FILTERS = {
    "fiscal_year",
    "quarter",
    "date_from",
    "date_to",
    "region",
    "currency",
}


def _fail(code: str, http_status: int = status.HTTP_422_UNPROCESSABLE_ENTITY):  # type: ignore[no-untyped-def]
    raise raise_api_error(http_status, code)


def _provided_filters(filters: Filters) -> dict:
    return filters.model_dump(exclude_unset=True, exclude_none=True)


def _check_filters(dataset: Dataset, filters: Filters) -> None:
    allowed = DATASETS[dataset].filters
    for name in _provided_filters(filters):
        if name not in allowed:
            _fail("invalid_filter")


def _check_group_by(dataset: Dataset, group_by: list[str]) -> None:
    allowed = DATASETS[dataset].groups
    for name in group_by:
        if name not in allowed:
            _fail("invalid_group_by")


def _provenance(
    *,
    dataset: str,
    operation: str,
    filters: Filters,
    group_by: list[str],
    company_id: uuid.UUID,
    record_count: int,
) -> Provenance:
    return Provenance(
        dataset=dataset,
        operation=operation,
        filters=_provided_filters(filters),
        group_by=list(group_by),
        company_id=company_id,
        record_count=record_count,
        calculated_at=datetime.now(timezone.utc),
    )


def _guard_currency(*groups: tuple[str, ...]) -> str | None:
    seen = {currency for group in groups for currency in group}
    if len(seen) > 1:
        _fail("mixed_currency")
    return next(iter(seen)) if seen else None


def _money(value: Decimal) -> str:
    return str(calc_math.quantize_money(value))


def _single(
    session: Session,
    *,
    company_id: uuid.UUID,
    request: CalculationRequest,
) -> SingleResult | GroupedResult:
    _check_filters(request.dataset, request.filters)
    if request.operation not in _SINGLE_OPS:
        _fail("unsupported_calculation")
    if request.group_by:
        _check_group_by(request.dataset, request.group_by)

    if not request.group_by:
        agg = repo.aggregate(
            session,
            dataset=request.dataset,
            company_id=company_id,
            filters=request.filters,
        )
        currency = _guard_currency(agg.currencies)
        base = dict(
            dataset=request.dataset.value,
            operation=request.operation.value,
            currency=currency,
            record_count=agg.count,
            provenance=_provenance(
                dataset=request.dataset.value,
                operation=request.operation.value,
                filters=request.filters,
                group_by=[],
                company_id=company_id,
                record_count=agg.count,
            ),
        )
        if request.operation == Operation.count:
            return SingleResult(
                **base, value=str(agg.count), unit="count", has_data=True, status="ok"
            )
        raw = {
            Operation.sum: agg.total,
            Operation.average: agg.average,
            Operation.minimum: agg.minimum,
            Operation.maximum: agg.maximum,
        }[request.operation]
        if raw is None:
            return SingleResult(
                **base, value=None, unit="money", has_data=False, status="no_data"
            )
        value = _money(raw)
        # DB AVG on NUMERIC already returns full-precision Decimal: quantize once.
        return SingleResult(
            **base, value=value, unit="money", has_data=True, status="ok"
        )

    rows = repo.aggregate_grouped(
        session,
        dataset=request.dataset,
        company_id=company_id,
        filters=request.filters,
        group_by=request.group_by,
    )
    if request.operation != Operation.sum and request.operation != Operation.count:
        _fail("unsupported_calculation")
    groups: list[GroupValue] = []
    total_records = 0
    for dims, total, count in rows:
        total_records += count
        if request.operation == Operation.count:
            groups.append(
                GroupValue(
                    dimensions=dict(zip(request.group_by, dims)),
                    value=str(count),
                    record_count=count,
                    has_data=True,
                )
            )
        else:
            groups.append(
                GroupValue(
                    dimensions=dict(zip(request.group_by, dims)),
                    value=_money(total) if total is not None else None,
                    record_count=count,
                    has_data=total is not None,
                )
            )
    unit = "count" if request.operation == Operation.count else "money"
    return GroupedResult(
        dataset=request.dataset.value,
        operation=request.operation.value,
        unit=unit,
        currency=None,
        groups=groups,
        record_count=total_records,
        status="ok" if groups else "no_data",
        provenance=_provenance(
            dataset=request.dataset.value,
            operation=request.operation.value,
            filters=request.filters,
            group_by=request.group_by,
            company_id=company_id,
            record_count=total_records,
        ),
    )


def _period_filters(base: Filters, period: Period, *, dataset: Dataset) -> Filters:
    """Inherit non-temporal dims; fiscal scope comes ONLY from the period."""
    provided = _provided_filters(base)
    temporal = {"fiscal_year", "quarter", "date_from", "date_to"}
    if provided.keys() & temporal:
        _fail("invalid_period")
    values = {
        name: value
        for name, value in provided.items()
        if name in DATASETS[dataset].filters
    }
    values["fiscal_year"] = period.fiscal_year
    if period.quarter is not None:
        values["quarter"] = period.quarter
    return Filters(**values)


def _auto_previous(period: Period) -> Period:
    """Previous fiscal year, same quarter shape. The only auto rule; documented."""
    return Period(fiscal_year=period.fiscal_year - 1, quarter=period.quarter)


def _comparison(
    session: Session,
    *,
    company_id: uuid.UUID,
    request: CalculationRequest,
    kind: str,
) -> ComparisonResult:
    if request.current_period is None:
        _fail("invalid_period")
    assert request.current_period is not None
    _check_filters(request.dataset, request.filters)
    comparison_period = request.comparison_period or _auto_previous(
        request.current_period
    )
    if (request.current_period.quarter is None) != (comparison_period.quarter is None):
        _fail("invalid_period")

    current_filters = _period_filters(
        request.filters, request.current_period, dataset=request.dataset
    )
    comparison_filters = _period_filters(
        request.filters, comparison_period, dataset=request.dataset
    )
    current = repo.aggregate(
        session, dataset=request.dataset, company_id=company_id, filters=current_filters
    )
    comparison = repo.aggregate(
        session,
        dataset=request.dataset,
        company_id=company_id,
        filters=comparison_filters,
    )
    currency = _guard_currency(current.currencies, comparison.currencies)
    record_count = current.count + comparison.count
    base = dict(
        dataset=request.dataset.value,
        operation=request.operation.value,
        currency=currency,
        record_count=record_count,
        current_period=request.current_period,
        comparison_period=comparison_period,
        provenance=_provenance(
            dataset=request.dataset.value,
            operation=request.operation.value,
            filters=request.filters,
            group_by=[],
            company_id=company_id,
            record_count=record_count,
        ),
    )
    if current.total is None or comparison.total is None:
        missing = "current period" if current.total is None else "comparison period"
        return ComparisonResult(
            **base,
            current_value=str(current.total) if current.total is not None else None,
            comparison_value=str(comparison.total)
            if comparison.total is not None
            else None,
            unit="money" if kind == "variance" else "percent",
            has_data=False,
            status="no_data",
            reason=f"no records in {missing}",
        )
    if kind == "variance":
        absolute = _money(current.total - comparison.total)
        percent, pstatus, reason = calc_math.variance_percent(
            current.total, comparison.total
        )
        return ComparisonResult(
            **base,
            current_value=_money(current.total),
            comparison_value=_money(comparison.total),
            absolute_variance=absolute,
            percent_value=str(percent) if percent is not None else None,
            unit="money",
            has_data=True,
            status="ok" if pstatus == "ok" else "undefined",
            reason=reason,
        )
    percent, pstatus, reason = calc_math.growth_percent(current.total, comparison.total)
    return ComparisonResult(
        **base,
        current_value=_money(current.total),
        comparison_value=_money(comparison.total),
        percent_value=str(percent) if percent is not None else None,
        unit="percent",
        has_data=True,
        status="ok" if pstatus == "ok" else "undefined",
        reason=reason,
    )


def _margin(
    session: Session, *, company_id: uuid.UUID, request: CalculationRequest
) -> MarginResult:
    for name in _provided_filters(request.filters):
        if name not in _MARGIN_FILTERS:
            _fail("invalid_filter")
    if request.group_by:
        _fail("unsupported_calculation")

    def scope(period: Period | None) -> Filters:
        provided = _provided_filters(request.filters)
        values = dict(provided)
        if period is not None:
            if values.keys() & {"fiscal_year", "quarter", "date_from", "date_to"}:
                _fail("invalid_period")
            values["fiscal_year"] = period.fiscal_year
            if period.quarter is not None:
                values["quarter"] = period.quarter
        return Filters(**values)

    scoped = scope(request.current_period)
    revenue = repo.aggregate(
        session, dataset=Dataset.revenue, company_id=company_id, filters=scoped
    )
    expense = repo.aggregate(
        session, dataset=Dataset.expense, company_id=company_id, filters=scoped
    )
    currency = _guard_currency(revenue.currencies, expense.currencies)
    record_count = revenue.count + expense.count
    base = dict(
        currency=currency,
        record_count=record_count,
        provenance=_provenance(
            dataset="revenue+expense",
            operation="margin",
            filters=request.filters,
            group_by=[],
            company_id=company_id,
            record_count=record_count,
        ),
    )
    if revenue.total is None and expense.total is None:
        return MarginResult(
            **base,
            revenue_value=None,
            expense_value=None,
            absolute_value=None,
            margin_percent=None,
            has_data=False,
            status="no_data",
            reason="no revenue or expense records in scope",
        )
    rev = revenue.total if revenue.total is not None else Decimal("0")
    exp = expense.total if expense.total is not None else Decimal("0")
    margin, mstatus, reason = calc_math.margin_percent(rev, exp)
    return MarginResult(
        **base,
        revenue_value=_money(revenue.total) if revenue.total is not None else None,
        expense_value=_money(expense.total) if expense.total is not None else None,
        absolute_value=_money(rev - exp),
        margin_percent=str(margin) if margin is not None else None,
        has_data=True,
        status="ok" if mstatus == "ok" else "undefined",
        reason=reason,
    )


def calculate(
    session: Session, *, company_id: uuid.UUID, request: CalculationRequest
) -> CalculationResponse:
    """Run one closed-vocabulary calculation. Read-only: never commits."""
    started = time.perf_counter()
    if request.operation in _SINGLE_OPS:
        result: CalculationResponse = _single(
            session, company_id=company_id, request=request
        )
    elif request.operation == Operation.growth_rate:
        result = _comparison(
            session, company_id=company_id, request=request, kind="growth"
        )
    elif request.operation == Operation.variance:
        result = _comparison(
            session, company_id=company_id, request=request, kind="variance"
        )
    elif request.operation == Operation.margin:
        if request.dataset != Dataset.revenue:
            _fail("unsupported_calculation")
        result = _margin(session, company_id=company_id, request=request)
    else:  # pragma: no cover - enum-closed dispatch
        _fail("unsupported_calculation")
    logger.info(
        "calculation dataset=%s operation=%s records=%s status=%s duration_ms=%s company_id=%s",
        request.dataset.value,
        request.operation.value,
        result.record_count,
        result.status,
        int((time.perf_counter() - started) * 1000),
        company_id,
    )
    return result
