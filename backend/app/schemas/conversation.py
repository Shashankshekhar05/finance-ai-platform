"""Conversation DTOs: threads, messages, bounded detail views.

No company_id anywhere: tenant scope comes only from the auth context.
Content limits mirror the threat model (untrusted stored text): titles are
short, message bodies bounded. No secrets, tokens, or system content exist
in these shapes by construction.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MessageRoleLiteral = Literal["user", "assistant"]


class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)


class ConversationRead(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    user_id: uuid.UUID
    title: str | None
    message_count: int
    created_at: datetime
    updated_at: datetime


class MessageRead(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    sequence: int
    created_at: datetime


class ConversationDetailRead(ConversationRead):
    messages: list[MessageRead] = []
