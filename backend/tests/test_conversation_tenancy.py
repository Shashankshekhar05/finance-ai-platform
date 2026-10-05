"""Conversation tenant isolation + same-company access model.

HTTP proves cross-tenant invisibility (uniform 404, scoped lists).
Service-level fixtures prove the owner-or-admin rule inside one company
(two users, one tenant — not reachable via public registration, which mints
one company per user).
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.db.engine import dispose_engine, get_engine, session_scope
from app.main import create_app
from app.models.user_role import Role
from app.repositories import (
    conversation_repository,
    membership_repository,
    user_repository,
)
from app.services import conversation_service
from app.services.tenancy import TenantContext
from tests.conftest import is_database_reachable, tenant_who

pytestmark = pytest.mark.skipif(
    not is_database_reachable(), reason="PostgreSQL not reachable at DATABASE_URL"
)


@pytest.fixture(scope="module")
def clients() -> TestClient:
    return TestClient(create_app())


@pytest.fixture(scope="module")
def tenant_a(clients: TestClient) -> dict:
    return tenant_who(clients, role="analyst")


@pytest.fixture(scope="module")
def tenant_b(clients: TestClient) -> dict:
    return tenant_who(clients, role="viewer")


def _thread(clients: TestClient, headers: dict, title: str = "Private") -> dict:
    response = clients.post("/conversations", json={"title": title}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def test_cross_tenant_conversation_invisible(
    clients: TestClient, tenant_a: dict, tenant_b: dict
) -> None:
    thread = _thread(clients, tenant_a["headers"])
    for method in ("get", "delete"):
        response = getattr(clients, method)(
            f"/conversations/{thread['id']}", headers=tenant_b["headers"]
        )
        assert response.status_code == 404, (method, response.text)
        assert response.json()["error"]["code"] == "not_found"


def test_cross_tenant_thread_absent_from_list(
    clients: TestClient, tenant_a: dict, tenant_b: dict
) -> None:
    thread = _thread(clients, tenant_a["headers"], title="A only")
    listed = clients.get("/conversations", headers=tenant_b["headers"]).json()
    assert all(item["company_id"] == tenant_b["company_id"] for item in listed["items"])
    assert thread["id"] not in {item["id"] for item in listed["items"]}


def test_cross_tenant_query_reference_is_foreign(
    clients: TestClient, tenant_a: dict, tenant_b: dict
) -> None:
    thread = _thread(clients, tenant_a["headers"])
    response = clients.post(
        "/ai/query",
        json={"question": "What was revenue?", "conversation_id": thread["id"]},
        headers=tenant_b["headers"],
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def _second_user_ctx(company_id: str) -> TenantContext:
    """Build a viewer TenantContext for a NEW user inside an existing company."""
    from app.models.company import Company

    engine = get_engine()
    try:
        with session_scope(engine) as session:
            user = user_repository.create(
                session,
                email=f"second-{uuid.uuid4().hex[:8]}@example.com",
                password_hash="not-a-real-hash",
                full_name="Second User",
            )
            membership_repository.create(
                session,
                user_id=user.id,
                company_id=uuid.UUID(company_id),
                role=Role.viewer,
            )
            session.refresh(user)
            company = session.get(Company, uuid.UUID(company_id))
            assert company is not None
            return TenantContext(
                user=user,
                company=company,
                role=Role.viewer,
                company_id=uuid.UUID(company_id),
            )
    finally:
        dispose_engine()


def test_same_company_non_owner_cannot_open_thread(
    clients: TestClient, tenant_a: dict
) -> None:
    thread = _thread(clients, tenant_a["headers"])
    other = _second_user_ctx(tenant_a["company_id"])
    engine = get_engine()
    try:
        with session_scope(engine) as session:
            from fastapi.exceptions import HTTPException

            with pytest.raises(HTTPException) as exc:
                conversation_service.get_conversation_detail(
                    session, ctx=other, conversation_id=uuid.UUID(thread["id"])
                )
            assert exc.value.status_code == 404
    finally:
        dispose_engine()


def test_same_company_admin_can_manage_thread(
    clients: TestClient, tenant_a: dict
) -> None:
    from app.models.company import Company

    # Promote a second in-company user to admin, then manage freely.
    other = _second_user_ctx(tenant_a["company_id"])
    thread = _thread(clients, tenant_a["headers"], title="Managed")
    engine = get_engine()
    try:
        with session_scope(engine) as session:
            memberships = membership_repository.list_for_user(
                session, user_id=other.user.id
            )
            assert len(memberships) == 1
            memberships[0].role = Role.admin
            db_user = user_repository.get_by_id(session, other.user.id)
            assert db_user is not None
            company = session.get(Company, other.company_id)
            assert company is not None
            admin_ctx = TenantContext(
                user=db_user,
                company=company,
                role=Role.admin,
                company_id=other.company_id,
            )
            detail = conversation_service.get_conversation_detail(
                session, ctx=admin_ctx, conversation_id=uuid.UUID(thread["id"])
            )
            assert detail.id == uuid.UUID(thread["id"])
            conversation_service.delete_conversation(
                session, ctx=admin_ctx, conversation_id=uuid.UUID(thread["id"])
            )
            assert (
                conversation_repository.get(
                    session,
                    company_id=other.company_id,
                    conversation_id=uuid.UUID(thread["id"]),
                )
                is None
            )
    finally:
        dispose_engine()


def test_foreign_user_object_rejected_even_with_valid_company(
    clients: TestClient, tenant_a: dict, tenant_b: dict
) -> None:
    """A TenantContext whose user is not a member resolves nothing: service
    layer still 404s because the row filter is (company AND owner-or-admin)."""
    thread = _thread(clients, tenant_a["headers"])
    other = _second_user_ctx(tenant_b["company_id"])
    engine = get_engine()
    try:
        with session_scope(engine) as session:
            from fastapi.exceptions import HTTPException

            with pytest.raises(HTTPException):
                conversation_service.get_conversation_detail(
                    session, ctx=other, conversation_id=uuid.UUID(thread["id"])
                )
    finally:
        dispose_engine()
