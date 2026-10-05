"""Shared pytest fixtures.

Live-DB tests are gated on reachability so the suite stays green with or
without PostgreSQL running; pure unit tests never need a database.
Auth tests use uuid-unique emails: isolated rows, no cross-test coupling.
"""

import socket
import uuid
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.core.config import get_settings
from app.db.engine import create_engine_for, dispose_engine, get_engine, session_scope
from app.main import create_app
from app.models.user_role import Role
from app.repositories import membership_repository, user_repository


def _tcp_reachable(host: str, port: int, timeout_s: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


def is_database_reachable() -> bool:
    """True when the configured DATABASE_URL host:port accepts TCP."""
    try:
        parsed = urlparse(str(get_settings().database_url))
    except Exception:
        return False
    if not parsed.hostname or not parsed.port:
        return False
    return _tcp_reachable(parsed.hostname, parsed.port)


requires_db = pytest.mark.skipif(
    not is_database_reachable(),
    reason="PostgreSQL not reachable at DATABASE_URL",
)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture()
def live_engine() -> Engine:
    """Engine against the real DATABASE_URL. Skips when DB is down."""
    if not is_database_reachable():
        pytest.skip("PostgreSQL not reachable at DATABASE_URL")
    engine = create_engine_for(str(get_settings().database_url))
    try:
        yield engine
    finally:
        engine.dispose()
        dispose_engine()


def unique_email(prefix: str = "test") -> str:
    return f"{prefix}+{uuid.uuid4().hex[:12]}@example.com"


def register_user(
    client: TestClient,
    *,
    email: str,
    password: str = "CorrectHorse123",
    full_name: str = "Test User",
) -> dict:
    response = client.post(
        "/auth/register",
        json={"email": email, "password": password, "full_name": full_name},
    )
    assert response.status_code == 201, response.text
    return response.json()


def login_token(
    client: TestClient, *, email: str, password: str = "CorrectHorse123"
) -> str:
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def promote_to_role(email: str, role: Role) -> None:
    """Set a user's (single) membership role. Test-only helper."""
    engine = get_engine()
    try:
        with session_scope(engine) as session:
            user = user_repository.get_by_email(session, email)
            assert user is not None
            memberships = membership_repository.list_for_user(session, user_id=user.id)
            assert len(memberships) == 1
            memberships[0].role = role
    finally:
        dispose_engine()


def tenant_who(client: TestClient, role: str = "viewer") -> dict:
    """Register → (optionally promote + re-login) → {token, company_id, user_id}."""
    email = unique_email(prefix=f"fin-{role}")
    user = register_user(client, email=email)
    if role != Role.viewer.value:
        promote_to_role(email, Role(role))
        token = login_token(client, email=email)
        response = client.get("/auth/me", headers=auth_headers(token))
        assert response.status_code == 200, response.text
        user = response.json()
    else:
        token = login_token(client, email=email)
    return {
        "token": token,
        "company_id": user["companies"][0]["company_id"],
        "user_id": user["id"],
        "headers": auth_headers(token),
    }
