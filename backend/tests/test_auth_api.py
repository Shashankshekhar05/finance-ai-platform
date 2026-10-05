"""Auth API: register / login / me against the live database.

Uses uuid-unique emails per test (isolated rows). Skips when PostgreSQL
is unreachable.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.jwt import create_access_token
from app.db.engine import dispose_engine, get_engine, get_session_factory
from app.repositories import user_repository
from app.schemas.auth import RegisterRequest
from app.services import auth_service
from tests.conftest import (
    auth_headers,
    is_database_reachable,
    login_token,
    register_user,
    unique_email,
)

pytestmark = pytest.mark.skipif(
    not is_database_reachable(), reason="PostgreSQL not reachable at DATABASE_URL"
)


def _envelope(response, *, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert body["error"]["code"] == code, body
    assert body["error"]["request_id"]
    assert "traceback" not in response.text.lower()


def test_register_success_creates_viewer_with_personal_company(
    client: TestClient,
) -> None:
    email = unique_email()
    response = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": "CorrectHorse123",
            "full_name": "Ada Lovelace",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["email"] == email
    assert body["full_name"] == "Ada Lovelace"
    assert body["is_active"] is True
    assert "password_hash" not in response.text
    assert "password" not in body
    assert len(body["companies"]) == 1
    assert body["companies"][0]["role"] == "viewer"
    assert body["companies"][0]["company_name"] == "Ada Lovelace's Workspace"


def test_register_normalizes_email(client: TestClient) -> None:
    email = unique_email()
    register_user(client, email=email)
    response = client.post(
        "/auth/register",
        json={
            "email": email.upper(),
            "password": "CorrectHorse123",
            "full_name": "Dup",
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "email_already_registered"


def test_register_duplicate_email_rejected(client: TestClient) -> None:
    email = unique_email()
    register_user(client, email=email)
    response = client.post(
        "/auth/register",
        json={"email": email, "password": "CorrectHorse123", "full_name": "Dup"},
    )
    _envelope(response, status=409, code="email_already_registered")


def test_register_invalid_input_rejected(client: TestClient) -> None:
    for payload in (
        {"email": "not-an-email", "password": "CorrectHorse123", "full_name": "X"},
        {"email": unique_email(), "password": "short", "full_name": "X"},
        {"email": unique_email(), "password": "CorrectHorse123", "full_name": ""},
        {"email": unique_email(), "password": "CorrectHorse123"},
    ):
        response = client.post("/auth/register", json=payload)
        _envelope(response, status=422, code="validation_error")


def test_registration_rolls_back_when_company_creation_fails(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A mid-transaction failure must leave NO user row behind."""
    from app.repositories import company_repository

    def _boom(session, *, name):  # type: ignore[no-untyped-def]
        raise RuntimeError("simulated company failure")

    monkeypatch.setattr(company_repository, "create", _boom)
    email = unique_email()
    try:
        with pytest.raises(RuntimeError, match="simulated company failure"):
            auth_service.register_user(
                get_session_factory(get_engine())(),
                RegisterRequest(
                    email=email, password="CorrectHorse123", full_name="No Company"
                ),
            )
    finally:
        dispose_engine()
    # Row must not exist: query with a fresh session.
    engine = get_engine()
    try:
        session = get_session_factory(engine)()
        try:
            assert user_repository.get_by_email(session, email) is None
        finally:
            session.close()
    finally:
        dispose_engine()
    _ = client  # exercised via service to inject the failure deterministically


def test_login_success_returns_bearer_token(client: TestClient) -> None:
    email = unique_email()
    register_user(client, email=email, password="CorrectHorse123")
    response = client.post(
        "/auth/login", json={"email": email, "password": "CorrectHorse123"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert "password_hash" not in response.text


def test_login_wrong_password_rejected_without_enumeration(client: TestClient) -> None:
    email = unique_email()
    register_user(client, email=email, password="CorrectHorse123")
    response = client.post(
        "/auth/login", json={"email": email, "password": "WrongPassword999"}
    )
    _envelope(response, status=401, code="invalid_credentials")


def test_login_unknown_email_returns_same_error(client: TestClient) -> None:
    response = client.post(
        "/auth/login",
        json={
            "email": f"nobody-{uuid.uuid4().hex}@example.com",
            "password": "Whatever123",
        },
    )
    _envelope(response, status=401, code="invalid_credentials")


def test_login_inactive_user_rejected(client: TestClient) -> None:
    email = unique_email()
    register_user(client, email=email, password="CorrectHorse123")
    engine = get_engine()
    try:
        session = get_session_factory(engine)()
        try:
            user = user_repository.get_by_email(session, email)
            assert user is not None
            user.is_active = False
            session.commit()
        finally:
            session.close()
    finally:
        dispose_engine()
    response = client.post(
        "/auth/login", json={"email": email, "password": "CorrectHorse123"}
    )
    _envelope(response, status=401, code="invalid_credentials")


def test_me_returns_safe_user(client: TestClient) -> None:
    email = unique_email()
    register_user(client, email=email)
    token = login_token(client, email=email)
    response = client.get("/auth/me", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["email"] == email
    assert len(body["companies"]) == 1
    assert "password_hash" not in response.text


def test_me_unauthenticated_rejected(client: TestClient) -> None:
    response = client.get("/auth/me")
    _envelope(response, status=401, code="authentication_required")


def test_me_malformed_token_rejected(client: TestClient) -> None:
    response = client.get("/auth/me", headers=auth_headers("not.a.token"))
    _envelope(response, status=401, code="invalid_token")


def test_me_tampered_token_rejected(client: TestClient) -> None:
    email = unique_email()
    register_user(client, email=email)
    token = login_token(client, email=email)
    tampered = token[:-2] + ("XX" if not token.endswith("XX") else "YY")
    response = client.get("/auth/me", headers=auth_headers(tampered))
    _envelope(response, status=401, code="invalid_token")


def test_me_expired_token_rejected(client: TestClient) -> None:
    email = unique_email()
    user = register_user(client, email=email)
    settings = get_settings()
    expired = create_access_token(
        user_id=user["id"],
        company_id=user["companies"][0]["company_id"],
        role="viewer",
        secret_key=settings.jwt_secret_key,
        expires_minutes=-1,
    )
    response = client.get("/auth/me", headers=auth_headers(expired))
    _envelope(response, status=401, code="token_expired")


def test_me_inactive_user_rejected(client: TestClient) -> None:
    email = unique_email()
    register_user(client, email=email)
    token = login_token(client, email=email)
    engine = get_engine()
    try:
        session = get_session_factory(engine)()
        try:
            user = user_repository.get_by_email(session, email)
            assert user is not None
            user.is_active = False
            session.commit()
        finally:
            session.close()
    finally:
        dispose_engine()
    response = client.get("/auth/me", headers=auth_headers(token))
    _envelope(response, status=401, code="inactive_user")
