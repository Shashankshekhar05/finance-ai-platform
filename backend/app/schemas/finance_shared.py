"""Shared finance primitives: money, currency, pagination, sorting.

Contracts (ARCHITECTURE.md money-as-string, DATABASE_RULES.md §2/§9):
- Amounts are Decimal with at most 2dp, positive, magnitude-guarded for
  NUMERIC(18,2). Responses serialize amounts as STRINGS (exact, no float).
- Currency is a 3-letter code, normalized to uppercase. Shape-validated
  only: full ISO-4217 registry validation is deferred (documented).
- Lists paginate (limit 1..200, default 50; offset >= 0) and sort only by
  allowlisted columns chosen per resource. Repos add id as a tiebreaker
  so default ordering is deterministic.
"""

import uuid
from decimal import Decimal
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
)

MAX_MONEY = Decimal("9999999999999999.99")  # NUMERIC(18,2) ceiling


def _check_positive_money(value: Decimal) -> Decimal:
    if not value.is_finite():
        raise ValueError("Amount must be finite.")
    if value <= 0:
        raise ValueError("Amount must be greater than zero.")
    if abs(value.as_tuple().exponent) > 2:
        raise ValueError("Amount must have at most 2 decimal places.")
    if value > MAX_MONEY:
        raise ValueError("Amount exceeds the maximum storable value.")
    return value


PositiveMoney = Annotated[Decimal, AfterValidator(_check_positive_money)]


def _normalize_currency(value: str) -> str:
    return value.strip().upper()


CurrencyCode = Annotated[
    str,
    AfterValidator(_normalize_currency),
    Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$"),
]


def _nonempty_or_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


# Optional analytic dimensions: blank strings become NULL (no '' sentinels).
def _none_if_blank(value: str | None) -> str | None:
    return _nonempty_or_none(value)


CleanLabel = Annotated[str | None, AfterValidator(_none_if_blank)]

Label100 = Annotated[CleanLabel, Field(max_length=100)]
Label200 = Annotated[CleanLabel, Field(max_length=200)]


class Pagination(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


SortOrder = Literal["asc", "desc"]

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """Consistent paginated envelope: items + total + echo of paging."""

    items: list[T]
    total: int
    limit: int
    offset: int


class FiscalFields(BaseModel):
    fiscal_year: int | None = Field(default=None, ge=1900, le=2100)
    fiscal_quarter: int | None = Field(default=None, ge=1, le=4)

    @field_validator("fiscal_quarter")
    @classmethod
    def quarter_needs_year(cls, value: int | None, info: ValidationInfo) -> int | None:
        if value is not None and (info.data.get("fiscal_year") is None):
            raise ValueError("fiscal_year is required when fiscal_quarter is set.")
        return value


class SourceFields(BaseModel):
    """Traceability stubs: documents table lands in a later phase (no FK yet)."""

    source_document_id: uuid.UUID | None = None
    source_page: int | None = Field(default=None, ge=1)
