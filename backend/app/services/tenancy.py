"""Tenant resolution: the ONLY place a request gains a company scope.

Rules (SECURITY_RULES.md §4, DATABASE_RULES.md §4):
- The trusted company comes from the verified JWT, never from the client.
- A client-supplied `company_id` that differs from the JWT scope is a
  hard 403 `tenant_mismatch` — it can never widen or switch scope.
- Membership is re-checked against user_roles on every resolution, so
  revoked grants take effect immediately (stale tokens fail closed).
- Every future company-owned query must start from `TenantContext`.
"""

import uuid
from dataclasses import dataclass

from fastapi import status
from sqlalchemy.orm import Session

from app.core.errors import raise_api_error
from app.models.company import Company
from app.models.user import User
from app.models.user_role import Role
from app.repositories import company_repository, membership_repository


@dataclass(frozen=True)
class TenantContext:
    user: User
    company: Company
    role: Role
    company_id: uuid.UUID


def _parse_uuid(raw: str, *, code: str = "tenant_mismatch") -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except (ValueError, AttributeError, TypeError):
        raise raise_api_error(status.HTTP_403_FORBIDDEN, code)


def resolve_tenant_context(
    session: Session,
    *,
    user: User,
    token_company_id: str,
    client_company_id: str | None = None,
) -> TenantContext:
    """Build the tenant scope for this request. Raises 403 on any mismatch."""
    token_cid = _parse_uuid(token_company_id)
    if client_company_id is not None and client_company_id != token_company_id:
        # Client scope must equal token scope; anything else is a bypass attempt.
        raise raise_api_error(status.HTTP_403_FORBIDDEN, "tenant_mismatch")

    membership = membership_repository.get_membership(
        session, user_id=user.id, company_id=token_cid
    )
    if membership is None:
        raise raise_api_error(status.HTTP_403_FORBIDDEN, "tenant_mismatch")
    company = company_repository.get_by_id(session, token_cid)
    if company is None:
        raise raise_api_error(status.HTTP_403_FORBIDDEN, "tenant_mismatch")
    return TenantContext(
        user=user, company=company, role=membership.role, company_id=token_cid
    )
