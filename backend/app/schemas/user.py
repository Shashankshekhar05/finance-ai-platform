"""Safe user DTOs: password_hash NEVER appears here by construction."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr


class CompanyMembershipRead(BaseModel):
    """One tenant grant. Built explicitly in the service layer."""

    company_id: uuid.UUID
    company_name: str
    role: str


class UserRead(BaseModel):
    """What /auth/register and /auth/me return. No secret fields exist."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str
    is_active: bool
    created_at: datetime
    companies: list[CompanyMembershipRead] = []
