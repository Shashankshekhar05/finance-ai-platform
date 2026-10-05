"""Role authorization: pure hierarchy matrix + real Depends wiring.

The Depends matrix runs against a throwaway FastAPI app that mounts the
PRODUCTION `require_*` dependencies — real wiring, no test doubles — with
users at each role level. Statuses asserted (probe app has no envelope
handlers, and this file only checks allow/deny).
"""

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.deps import require_admin, require_analyst, require_viewer
from app.db.engine import dispose_engine, get_engine, session_scope
from app.models.user_role import Role
from app.repositories import membership_repository, user_repository
from app.services.permissions import role_satisfies
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

probe = FastAPI()


@probe.get("/needs-viewer")
def _needs_viewer(ctx=Depends(require_viewer)):  # type: ignore[no-untyped-def]
    return {"role": ctx.role.value}


@probe.get("/needs-analyst")
def _needs_analyst(ctx=Depends(require_analyst)):  # type: ignore[no-untyped-def]
    return {"role": ctx.role.value}


@probe.get("/needs-admin")
def _needs_admin(ctx=Depends(require_admin)):  # type: ignore[no-untyped-def]
    return {"role": ctx.role.value}


@pytest.mark.parametrize(
    ("actual", "required", "expected"),
    [
        ("viewer", "viewer", True),
        ("analyst", "viewer", True),
        ("admin", "viewer", True),
        ("viewer", "analyst", False),
        ("analyst", "analyst", True),
        ("admin", "analyst", True),
        ("viewer", "admin", False),
        ("analyst", "admin", False),
        ("admin", "admin", True),
    ],
)
def test_role_hierarchy_matrix(actual: str, required: str, expected: bool) -> None:
    assert role_satisfies(Role(actual), Role(required)) is expected


def _promote(email: str, role: Role) -> None:
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


def _tokens_for_all_roles(client: TestClient) -> dict[str, str]:
    tokens = {}
    for role in (Role.viewer, Role.analyst, Role.admin):
        email = unique_email(prefix=f"role-{role.value}")
        register_user(client, email=email)
        if role is not Role.viewer:
            _promote(email, role)
        tokens[role.value] = login_token(client, email=email)
    return tokens


@pytest.mark.parametrize(
    ("role", "path", "expected"),
    [
        ("viewer", "/needs-viewer", 200),
        ("viewer", "/needs-analyst", 403),
        ("viewer", "/needs-admin", 403),
        ("analyst", "/needs-viewer", 200),
        ("analyst", "/needs-analyst", 200),
        ("analyst", "/needs-admin", 403),
        ("admin", "/needs-viewer", 200),
        ("admin", "/needs-analyst", 200),
        ("admin", "/needs-admin", 200),
    ],
)
def test_dependency_role_matrix(
    client: TestClient, role: str, path: str, expected: int
) -> None:
    tokens = _tokens_for_all_roles(client)
    probe_client = TestClient(probe)
    response = probe_client.get(path, headers=auth_headers(tokens[role]))
    assert response.status_code == expected, response.text


def test_guarded_endpoints_reject_missing_token() -> None:
    probe_client = TestClient(probe)
    for path in ("/needs-viewer", "/needs-analyst", "/needs-admin"):
        assert probe_client.get(path).status_code == 401
