"""Tenant isolation: JWT scope wins, client input never does.

Proves at the service layer (the same code future finance/document routes
will call): cross-company access fails closed, revoked grants fail closed,
and a matching client value passes through WITHOUT changing the scope.
"""

import uuid

import pytest
from fastapi import HTTPException

from app.db.engine import dispose_engine, get_engine, session_scope
from app.repositories import membership_repository, user_repository
from app.services.tenancy import resolve_tenant_context
from tests.conftest import is_database_reachable, register_user, unique_email

pytestmark = pytest.mark.skipif(
    not is_database_reachable(), reason="PostgreSQL not reachable at DATABASE_URL"
)


def _ids(email: str) -> tuple[uuid.UUID, uuid.UUID]:
    engine = get_engine()
    try:
        with session_scope(engine) as session:
            user = user_repository.get_by_email(session, email)
            assert user is not None
            memberships = membership_repository.list_for_user(session, user_id=user.id)
            assert len(memberships) == 1
            return user.id, memberships[0].company_id
    finally:
        dispose_engine()


def test_client_company_id_cannot_reach_another_company(client) -> None:  # type: ignore[no-untyped-def]
    email_a, email_b = unique_email("tenant-a"), unique_email("tenant-b")
    register_user(client, email=email_a)
    register_user(client, email=email_b)
    user_a_id, _ = _ids(email_a)
    _, company_b_id = _ids(email_b)

    engine = get_engine()
    try:
        with session_scope(engine) as session:
            user_a = user_repository.get_by_id(session, user_a_id)
            assert user_a is not None
            # No membership row exists across tenants at the repository level.
            assert (
                membership_repository.get_membership(
                    session, user_id=user_a_id, company_id=company_b_id
                )
                is None
            )
    finally:
        dispose_engine()


def test_resolve_rejects_foreign_client_company_id(client) -> None:  # type: ignore[no-untyped-def]
    email_a, email_b = unique_email("tenant-a"), unique_email("tenant-b")
    register_user(client, email=email_a)
    register_user(client, email=email_b)
    user_a_id, company_a_id = _ids(email_a)
    _, company_b_id = _ids(email_b)

    engine = get_engine()
    try:
        with session_scope(engine) as session:
            user_a = user_repository.get_by_id(session, user_a_id)
            assert user_a is not None
            with pytest.raises(HTTPException) as exc:
                resolve_tenant_context(
                    session,
                    user=user_a,
                    token_company_id=str(company_a_id),
                    client_company_id=str(company_b_id),
                )
            assert exc.value.status_code == 403
            assert exc.value.detail == "tenant_mismatch"
    finally:
        dispose_engine()


def test_resolve_matching_client_value_keeps_token_scope(client) -> None:  # type: ignore[no-untyped-def]
    email_a = unique_email("tenant-a")
    register_user(client, email=email_a)
    user_a_id, company_a_id = _ids(email_a)

    engine = get_engine()
    try:
        with session_scope(engine) as session:
            user_a = user_repository.get_by_id(session, user_a_id)
            assert user_a is not None
            ctx = resolve_tenant_context(
                session,
                user=user_a,
                token_company_id=str(company_a_id),
                client_company_id=str(company_a_id),
            )
            # Scope comes from the token grant, echoed — never from the client.
            assert ctx.company_id == company_a_id
            assert ctx.user.id == user_a_id
            assert ctx.role.value == "viewer"
    finally:
        dispose_engine()


def test_resolve_fails_closed_after_grant_revoked(client) -> None:  # type: ignore[no-untyped-def]
    email_a = unique_email("tenant-a")
    register_user(client, email=email_a)
    user_a_id, company_a_id = _ids(email_a)

    engine = get_engine()
    try:
        with session_scope(engine) as session:
            memberships = membership_repository.list_for_user(
                session, user_id=user_a_id
            )
            for membership in memberships:
                session.delete(membership)
        with session_scope(engine) as session:
            user_a = user_repository.get_by_id(session, user_a_id)
            assert user_a is not None
            with pytest.raises(HTTPException) as exc:
                resolve_tenant_context(
                    session, user=user_a, token_company_id=str(company_a_id)
                )
            assert exc.value.status_code == 403
            assert exc.value.detail == "tenant_mismatch"
    finally:
        dispose_engine()
