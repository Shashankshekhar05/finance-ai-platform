"""API-layer dependencies: auth, tenancy, and role guards.

Routes import from here — never from services/repositories directly — so
`authenticate → authorize → scope` stays one ordered pipeline.
`get_db` (request session) is re-exported for route signatures.
"""

import uuid

from fastapi import Depends, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import raise_api_error
from app.core.jwt import TokenExpiredError, TokenInvalidError, decode_and_validate
from app.db.engine import get_db
from app.models.company import Company
from app.models.user import User
from app.models.user_role import Role
from app.repositories import user_repository
from app.services.groq_client import GroqClient
from app.services.permissions import role_satisfies
from app.services.tenancy import TenantContext, resolve_tenant_context

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def _verified_claims(token: str) -> dict[str, object]:
    try:
        return decode_and_validate(token, secret_key=get_settings().jwt_secret_key)
    except TokenExpiredError:
        raise raise_api_error(status.HTTP_401_UNAUTHORIZED, "token_expired")
    except TokenInvalidError:
        raise raise_api_error(status.HTTP_401_UNAUTHORIZED, "invalid_token")


def get_current_user(
    token: str = Depends(oauth2_scheme), session: Session = Depends(get_db)
) -> User:
    claims = _verified_claims(token)
    try:
        user_id = uuid.UUID(str(claims["sub"]))
    except (ValueError, AttributeError, TypeError):
        raise raise_api_error(status.HTTP_401_UNAUTHORIZED, "invalid_token")
    user = user_repository.get_by_id(session, user_id)
    if user is None:
        raise raise_api_error(status.HTTP_401_UNAUTHORIZED, "invalid_token")
    if not user.is_active:
        raise raise_api_error(status.HTTP_401_UNAUTHORIZED, "inactive_user")
    return user


def get_tenant_context(
    user: User = Depends(get_current_user),
    token: str = Depends(oauth2_scheme),
    session: Session = Depends(get_db),
) -> TenantContext:
    claims = _verified_claims(token)
    return resolve_tenant_context(
        session, user=user, token_company_id=str(claims["company_id"])
    )


def get_current_company(
    ctx: TenantContext = Depends(get_tenant_context),
) -> Company:
    return ctx.company


def _check_role(ctx: TenantContext, required: Role) -> TenantContext:
    if not role_satisfies(ctx.role, required):
        raise raise_api_error(status.HTTP_403_FORBIDDEN, "insufficient_permissions")
    return ctx


def require_viewer(
    ctx: TenantContext = Depends(get_tenant_context),
) -> TenantContext:
    return _check_role(ctx, Role.viewer)


def require_analyst(
    ctx: TenantContext = Depends(get_tenant_context),
) -> TenantContext:
    return _check_role(ctx, Role.analyst)


def require_admin(
    ctx: TenantContext = Depends(get_tenant_context),
) -> TenantContext:
    return _check_role(ctx, Role.admin)


def get_llm_client() -> GroqClient:
    """Provider client for routes. Missing key fails closed (503) at call
    time — never at import. Tests override this dependency with a fake."""
    from app.services.groq_client import HttpGroqClient

    settings = get_settings()
    if settings.groq_api_key is None:
        raise raise_api_error(status.HTTP_503_SERVICE_UNAVAILABLE, "llm_unavailable")
    return HttpGroqClient(
        api_key=settings.groq_api_key, base_url=settings.groq_base_url
    )


__all__ = [
    "get_db",
    "get_settings",
    "get_current_user",
    "get_tenant_context",
    "get_current_company",
    "require_viewer",
    "require_analyst",
    "require_admin",
    "get_llm_client",
]
