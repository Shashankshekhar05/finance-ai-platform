"""Expense DTOs. Category required; amounts Decimal in, strings out."""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.finance_shared import (
    CleanLabel,
    CurrencyCode,
    FiscalFields,
    Label100,
    Label200,
    PositiveMoney,
    SourceFields,
)

ExpenseSort = Literal["record_date", "amount", "created_at"]


class ExpenseCreate(FiscalFields, SourceFields):
    model_config = ConfigDict(extra="forbid")

    amount: PositiveMoney
    currency: CurrencyCode
    record_date: date
    category: str = Field(min_length=1, max_length=100)
    department: Label100 = None
    region: Label100 = None
    vendor: Label200 = None
    description: str | None = Field(default=None, max_length=1000)


class ExpenseUpdate(FiscalFields, SourceFields):
    """Partial update. fiscal_quarter requires fiscal_year in the same payload."""

    model_config = ConfigDict(extra="forbid")

    amount: PositiveMoney | None = None
    currency: CurrencyCode | None = None
    record_date: date | None = None
    category: str | None = Field(default=None, min_length=1, max_length=100)
    department: Label100 = None
    region: Label100 = None
    vendor: Label200 = None
    description: str | None = Field(default=None, max_length=1000)


class ExpenseRead(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    amount: str
    currency: str
    record_date: date
    fiscal_year: int | None
    fiscal_quarter: int | None
    category: str
    department: str | None
    region: str | None
    vendor: str | None
    description: str | None
    source_document_id: uuid.UUID | None
    source_page: int | None
    created_at: datetime
    updated_at: datetime


class ExpenseFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date_from: date | None = None
    date_to: date | None = None
    fiscal_year: int | None = None
    fiscal_quarter: int | None = None
    category: CleanLabel = None
    department: CleanLabel = None
    region: CleanLabel = None
    sort: ExpenseSort = "record_date"
