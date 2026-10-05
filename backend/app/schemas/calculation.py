"""Calculation DTOs: closed vocabularies, validated filters, typed results.

Conventions:
- Datasets/operations/fields are enums or Literals — never table/column names.
- Money travels as Decimal in Python and exact STRINGS in JSON (project
  convention); percentages are strings meaning percent (unit="percent").
- date_from/date_to are INCLUSIVE. Revenue/expense use DATE semantics;
  transactions use UTC instants (existing model types, unchanged).
- `quarter` requires `fiscal_year` (existing finance-domain rule).
- No company_id field exists anywhere here: tenant scope comes only from
  the authenticated context (route layer).
"""

import uuid
from datetime import date, datetime
from enum import Enum
from typing import Annotated, Any, Literal, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class Dataset(str, Enum):
    revenue = "revenue"
    expense = "expense"
    transaction = "transaction"


class Operation(str, Enum):
    sum = "sum"
    count = "count"
    average = "average"
    minimum = "minimum"
    maximum = "maximum"
    growth_rate = "growth_rate"
    variance = "variance"
    margin = "margin"


class Filters(BaseModel):
    """Superset of per-dataset filters; each dataset validates its subset."""

    model_config = ConfigDict(extra="forbid")

    fiscal_year: int | None = Field(default=None, ge=1900, le=2100)
    quarter: int | None = Field(default=None, ge=1, le=4)
    date_from: date | datetime | None = None
    date_to: date | datetime | None = None
    category: str | None = Field(default=None, min_length=1, max_length=100)
    segment: str | None = Field(default=None, min_length=1, max_length=100)
    region: str | None = Field(default=None, min_length=1, max_length=100)
    department: str | None = Field(default=None, min_length=1, max_length=100)
    vendor: str | None = Field(default=None, min_length=1, max_length=200)
    transaction_type: Literal["income", "expense", "transfer"] | None = None
    account: str | None = Field(default=None, min_length=1, max_length=100)
    currency: str | None = Field(default=None, min_length=3, max_length=3)

    @field_validator("currency")
    @classmethod
    def _upper_currency(cls, value: str | None) -> str | None:
        return value.upper() if value is not None else None

    @model_validator(mode="after")
    def _check_ranges(self) -> "Filters":
        if self.quarter is not None and self.fiscal_year is None:
            raise ValueError("fiscal_year is required when quarter is set.")
        if (
            self.date_from is not None
            and self.date_to is not None
            and self.date_from > self.date_to
        ):
            raise ValueError("date_from must not be after date_to.")
        return self


class Period(BaseModel):
    """One explicit fiscal period. Quarter never stands alone."""

    model_config = ConfigDict(extra="forbid")

    fiscal_year: int = Field(ge=1900, le=2100)
    quarter: int | None = Field(default=None, ge=1, le=4)


class CalculationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset: Dataset = Dataset.revenue
    operation: Operation
    filters: Filters = Filters()
    group_by: list[str] = Field(default_factory=list, max_length=2)
    # Comparison ops: explicit periods. Omitted comparison_period means
    # "previous fiscal year, same quarter shape" (documented auto rule).
    current_period: Period | None = None
    comparison_period: Period | None = None


class Provenance(BaseModel):
    dataset: str
    operation: str
    filters: dict[str, Any]
    group_by: list[str]
    company_id: uuid.UUID
    record_count: int
    source_type: str = "structured_finance"
    calculated_at: datetime


class SingleResult(BaseModel):
    kind: Literal["single"] = "single"
    dataset: str
    operation: str
    # Money/percent as exact string; null when has_data is false.
    value: str | None
    unit: str  # "money" | "count" | "percent"
    currency: str | None = None
    has_data: bool
    record_count: int
    status: str  # "ok" | "no_data"
    provenance: Provenance


class GroupValue(BaseModel):
    dimensions: dict[str, str | None]
    value: str | None
    record_count: int
    has_data: bool


class GroupedResult(BaseModel):
    kind: Literal["grouped"] = "grouped"
    dataset: str
    operation: str
    unit: str
    currency: str | None = None
    groups: list[GroupValue]
    record_count: int
    status: str
    provenance: Provenance


class ComparisonResult(BaseModel):
    kind: Literal["comparison"] = "comparison"
    dataset: str
    operation: str
    current_value: str | None
    comparison_value: str | None
    absolute_variance: str | None = None
    percent_value: str | None = None  # growth_% or variance_%; null if undefined
    unit: str  # "money" for variance absolutes context, "percent" for growth
    currency: str | None = None
    has_data: bool
    record_count: int
    # "ok" | "no_data" | "undefined" (zero denominator; reason explains).
    status: str
    reason: str | None = None
    current_period: Period | None = None
    comparison_period: Period | None = None
    provenance: Provenance


class MarginResult(BaseModel):
    kind: Literal["margin"] = "margin"
    operation: str = "margin"
    revenue_value: str | None
    expense_value: str | None
    absolute_value: str | None  # revenue - expense ("profit" in eval terms)
    margin_percent: str | None  # null when revenue == 0
    unit: str = "percent"
    currency: str | None = None
    has_data: bool
    record_count: int
    status: str  # "ok" | "no_data" | "undefined"
    reason: str | None = None
    provenance: Provenance


CalculationResponse = Annotated[
    Union[SingleResult, GroupedResult, ComparisonResult, MarginResult],
    Field(discriminator="kind"),
]
