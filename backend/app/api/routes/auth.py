"""Auth routes. Thin by rule: validate → one service call → typed DTO.

- POST /auth/register (201): create user + personal company + viewer grant.
- POST /auth/login (200): verify credentials, return bearer token.
- GET  /auth/me (200): current user + memberships. Requires Bearer token.

Never returns password_hash; failures use the shared error envelope.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_settings
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse
from app.schemas.user import UserRead
from app.services import auth_service

router = APIRouter(tags=["auth"])


@router.post(
    "/auth/register", response_model=UserRead, status_code=status.HTTP_201_CREATED
)
def register(payload: RegisterRequest, session: Session = Depends(get_db)) -> UserRead:
    return auth_service.register_user(session, payload)


@router.post("/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest, session: Session = Depends(get_db)) -> TokenResponse:
    token = auth_service.authenticate(session, payload, get_settings())
    return TokenResponse(access_token=token)


@router.get("/auth/me", response_model=UserRead)
def me(
    user: User = Depends(get_current_user), session: Session = Depends(get_db)
) -> UserRead:
    return auth_service.get_safe_user(session, user)
