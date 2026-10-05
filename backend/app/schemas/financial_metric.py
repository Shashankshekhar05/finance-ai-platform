"""Financial-metric DTOs. No create/update API in Phase 3 (read-only);
writes go through `MetricRecordInput` at the service layer (tests today,
the deterministic calculation engine tomorrow)."""

import json
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from app.models.financial_metric import ComputedBy
from app.schemas.finance_shared import CleanLabel

MetricSort = Literal["period", "metric_name", "value"]
MAX_METRIC_VALUE = Decimal("9999999999999999.99999999")  # NUMERIC(24,8) ceiling


def _check_metric_value(value: Decimal) -> Decimal:
    if not value.is_finite():
        raise ValueError("Metric value must be finite.")
    if abs(value) > MAX_METRIC_VALUE:
        raise ValueError("Metric value exceeds the maximum storable value.")
    return value


class MetricRecordInput(BaseModel):
    """Service-layer input for recording a metric (not an HTTP body)."""

    model_config = ConfigDict(extra="forbid")

    period: date
    metric_name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    value: Decimal
    unit: str | None = Field(default=None, min_length=1, max_length=16)
    computed_by: ComputedBy = ComputedBy.reported
    inputs_ref: dict[str, Any] | None = None

    @field_validator("value")
    @classmethod
    def validate_value(cls, value: Decimal) -> Decimal:
        return _check_metric_value(value)

    @field_validator("inputs_ref")
    @classmethod
    def validate_inputs_ref(
        cls, value: dict[str, Any] | None, info: ValidationInfo
    ) -> dict[str, Any] | None:
        if info.data.get("computed_by") == ComputedBy.calculated and not value:
            raise ValueError("inputs_ref is required for calculated metrics.")
        if value is not None:
            try:
                json.dumps(value)
            except (TypeError, ValueError):
                raise ValueError("inputs_ref must be JSON-serializable.")
        return value


class MetricRead(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    period: date
    metric_name: str
    value: str
    unit: str | None
    computed_by: str
    inputs_ref: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class MetricFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric_name: CleanLabel = None
    period_from: date | None = None
    period_to: date | None = None
    computed_by: ComputedBy | None = None
    sort: MetricSort = "period"
