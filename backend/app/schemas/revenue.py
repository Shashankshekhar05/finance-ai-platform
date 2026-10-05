"""Revenue DTOs. Amounts in as Decimal, out as exact strings (no float)."""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.schemas.finance_shared import (
    CleanLabel,
    CurrencyCode,
    FiscalFields,
    Label100,
    PositiveMoney,
    SourceFields,
)

RevenueSort = Literal["record_date", "amount", "created_at"]


class RevenueCreate(FiscalFields, SourceFields):
    model_config = ConfigDict(extra="forbid")

    amount: PositiveMoney
    currency: CurrencyCode
    record_date: date
    segment: Label100 = None
    region: Label100 = None
    category: Label100 = None


class RevenueUpdate(FiscalFields, SourceFields):
    """Partial update. If fiscal_quarter is sent, fiscal_year must ride along
    in the same payload (payload-level rule; row state is not merged here)."""

    model_config = ConfigDict(extra="forbid")

    amount: PositiveMoney | None = None
    currency: CurrencyCode | None = None
    record_date: date | None = None
    segment: Label100 = None
    region: Label100 = None
    category: Label100 = None


class RevenueRead(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    amount: str
    currency: str
    record_date: date
    fiscal_year: int | None
    fiscal_quarter: int | None
    segment: str | None
    region: str | None
    category: str | None
    source_document_id: uuid.UUID | None
    source_page: int | None
    created_at: datetime
    updated_at: datetime


class RevenueFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date_from: date | None = None
    date_to: date | None = None
    fiscal_year: int | None = None
    fiscal_quarter: int | None = None
    region: CleanLabel = None
    segment: CleanLabel = None
    category: CleanLabel = None
    sort: RevenueSort = "record_date"
