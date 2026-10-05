"""Transaction DTOs. Type is a closed domain; direction from type, not sign."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.transaction import TransactionType
from app.schemas.finance_shared import (
    CleanLabel,
    CurrencyCode,
    Label100,
    Label200,
    PositiveMoney,
    SourceFields,
)

TransactionSort = Literal["occurred_at", "amount", "created_at"]


class TransactionCreate(SourceFields):
    model_config = ConfigDict(extra="forbid")

    occurred_at: datetime
    amount: PositiveMoney
    currency: CurrencyCode
    type: TransactionType
    category: Label100 = None
    account: Label100 = None
    description: str | None = Field(default=None, max_length=1000)
    reference: Label200 = None


class TransactionUpdate(SourceFields):
    model_config = ConfigDict(extra="forbid")

    occurred_at: datetime | None = None
    amount: PositiveMoney | None = None
    currency: CurrencyCode | None = None
    type: TransactionType | None = None
    category: Label100 = None
    account: Label100 = None
    description: str | None = Field(default=None, max_length=1000)
    reference: Label200 = None


class TransactionRead(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    occurred_at: datetime
    amount: str
    currency: str
    type: str
    category: str | None
    account: str | None
    description: str | None
    reference: str | None
    source_document_id: uuid.UUID | None
    source_page: int | None
    created_at: datetime
    updated_at: datetime


class TransactionFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date_from: datetime | None = None
    date_to: datetime | None = None
    type: TransactionType | None = None
    category: CleanLabel = None
    account: CleanLabel = None
    sort: TransactionSort = "occurred_at"
