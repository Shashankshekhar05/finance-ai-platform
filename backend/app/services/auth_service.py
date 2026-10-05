"""Auth service: register / authenticate / safe user views.

Layering: repositories for SQL, here for decisions. Raises HTTPException
domain errors (via `raise_api_error`); routes only map them to responses.
Registration is ONE transaction: user + personal company + viewer grant
commit together or roll back together (DATABASE_RULES.md §7A).

Login never reveals which step failed: unknown email, wrong password, and
inactive account all return 401 `invalid_credentials` (no enumeration).
"""

import logging

from fastapi import status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import raise_api_error
from app.core.jwt import create_access_token
from app.core.security import hash_password, verify_password
from app.models.user import User
from app.models.user_role import Role
from app.repositories import company_repository, membership_repository, user_repository
from app.schemas.auth import LoginRequest, RegisterRequest
from app.schemas.user import CompanyMembershipRead, UserRead

logger = logging.getLogger(__name__)


def _to_user_read(user: User) -> UserRead:
    companies = [
        CompanyMembershipRead(
            company_id=m.company_id,
            company_name=m.company.name,
            role=m.role.value,
        )
        for m in user.memberships
    ]
    return UserRead(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        created_at=user.created_at,
        companies=companies,
    )


def _personal_company_name(full_name: str) -> str:
    base = (full_name or "").strip() or "Personal"
    return f"{base[:180]}'s Workspace"


def register_user(session: Session, payload: RegisterRequest) -> UserRead:
    """Create user + personal company + viewer grant atomically."""
    if user_repository.get_by_email(session, payload.email) is not None:
        raise raise_api_error(status.HTTP_409_CONFLICT, "email_already_registered")
    try:
        user = user_repository.create(
            session,
            email=payload.email,
            password_hash=hash_password(payload.password),
            full_name=payload.full_name.strip(),
        )
        company = company_repository.create(
            session, name=_personal_company_name(payload.full_name)
        )
        membership_repository.create(
            session, user_id=user.id, company_id=company.id, role=Role.viewer
        )
        session.commit()
    except IntegrityError:
        # Race on the UNIQUE(email) guard: same safe answer as the pre-check.
        session.rollback()
        raise raise_api_error(status.HTTP_409_CONFLICT, "email_already_registered")
    except Exception:
        session.rollback()
        raise
    logger.info("user registered user_id=%s company_id=%s", user.id, company.id)
    session.refresh(user)
    return _to_user_read(user)


def authenticate(session: Session, payload: LoginRequest, settings: Settings) -> str:
    """Verify credentials and mint an access token. Uniform 401 on any failure."""
    user = user_repository.get_by_email(session, payload.email)
    if (
        user is None
        or not user.is_active
        or not verify_password(payload.password, user.password_hash)
    ):
        raise raise_api_error(status.HTTP_401_UNAUTHORIZED, "invalid_credentials")
    memberships = membership_repository.list_for_user(session, user_id=user.id)
    if not memberships:
        # Valid credentials but no tenant grant: fail closed, same generic code.
        raise raise_api_error(status.HTTP_401_UNAUTHORIZED, "invalid_credentials")
    active = memberships[0]
    logger.info("user login user_id=%s", user.id)
    return create_access_token(
        user_id=str(user.id),
        company_id=str(active.company_id),
        role=active.role.value,
        secret_key=settings.jwt_secret_key,
        expires_minutes=settings.access_token_expire_minutes,
    )


def get_safe_user(session: Session, user: User) -> UserRead:
    session.refresh(user)
    return _to_user_read(user)
